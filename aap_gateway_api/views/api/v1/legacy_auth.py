from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from django.contrib.auth import login
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from aap_gateway_api.models import MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, User
from aap_gateway_api.serializers.legacy_auth import LegacyAuthSerializer, RenameAccountSerializer, UsernamePasswordSerializer
from aap_gateway_api.utils.resources_client import GWResourceAPIClient
from aap_gateway_api.utils.service_token import validate_service_token
from aap_gateway_api.utils.user_migration import can_accounts_be_merged, link_account, migrate_account

UNMIGRATED_AUTH_SESSION_KEY = "partially_authed_user"


class LegacyAuthViewset(viewsets.ViewSet):
    permission_classes = []
    serializer_class = serializers.Serializer

    def list(self, request):
        user = self._get_user(request)
        if not user:
            resp = LegacyAuthSerializer()
        else:
            resp = LegacyAuthSerializer(
                user,
                context={
                    "request": request,
                    "needs_rename": self._needs_rename(user),
                },
            )
        return Response(resp.data)

    @action(detail=False, methods=["POST"], serializer_class=RenameAccountSerializer)
    def finalize(self, request):
        main_account = self._get_user(request)

        if not main_account:
            return redirect(get_relative_url("legacy_auth-list"))

        serializer = RenameAccountSerializer(data=request.data, context={'needs_rename': self._needs_rename(main_account)})
        serializer.is_valid(raise_exception=True)

        new_username = serializer.data.get("new_username", None)

        if new_username:
            try:
                main_account.username = new_username
                main_account.save()
            except IntegrityError:
                raise DRFValidationError({"new_username": _("%(new_username)s has already been taken.") % {"new_username": new_username}})

        self._migrate_account(main_account)
        self.request.session.flush()
        login(request, main_account)
        return redirect(get_relative_url("legacy_auth-list"))

    @action(detail=False, methods=["POST"], serializer_class=UsernamePasswordSerializer)
    def authenticate_password(self, request):
        serializer = UsernamePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            service = ServiceAPIRoute.objects.get(service_cluster__service_type=data["service_type"])
        except ServiceAPIRoute.DoesNotExist:
            raise DRFValidationError(
                {"service_type": _("Service type %(service_type)s does not exist.") % {"service_type": data['service_type']}},
            )

        client = GWResourceAPIClient(
            service=service,
            raise_if_bad_request=False,
        )

        response = client.validate_local_user(username=data["username"], password=data["password"])
        if response.status_code != 200:
            raise DRFValidationError(_("Invalid username or password."))

        auth_code = response.json()["auth_code"]
        self._handle_auth_code(auth_code, auth_type="password")

        return redirect(get_relative_url("legacy_auth-list"))

    @action(detail=False, methods=["GET"])
    def authenticate_sso(self, request):
        auth_code = request.GET.get("auth_code", None)

        if auth_code is not None:
            self._handle_auth_code(auth_code, auth_type="sso")

        return redirect(get_relative_url("legacy_auth-list"))

    @action(detail=False, methods=["POST"])
    def reset(self, request):
        request.session.flush()
        return redirect(get_relative_url("legacy_auth-list"))

    def _handle_auth_code(self, auth_code, auth_type):
        # Check that the auth code is valid and load the user.
        try:
            data = validate_service_token(auth_code, required_type="auth_code")
            self._is_allowed_to_login(data, auth_type)
        except ValidationError as e:
            # TODO: return something helpful here
            raise DRFValidationError(e.message)

        user = data["user"]
        payload = data["token_data"]["payload"]

        # add a migration entry for the user
        if not user.original_accounts.exists():
            MigratedUserMetadata.objects.create(
                user=user,
                service=data["service_cluster"],
                original_username=payload["username"],
            )

            authenticator_meta = MigratedAuthenticatorMetadata.get_authenticator_for_auth_code(data)

            AuthenticatorUser.objects.create(
                user=user,
                provider=authenticator_meta.authenticator,
                uid=payload.get("uid", user.username),
            )

        session_user = self._get_user(self.request)

        if not session_user:
            self._authenticate_user(user)
        else:
            self._link_account(session_user, user)

    def _get_user(self, request):
        if request.user and not isinstance(request.user, AnonymousUser):
            return request.user
        if unmigrated_id := request.session.get(UNMIGRATED_AUTH_SESSION_KEY):
            try:
                return User.objects.get(pk=unmigrated_id)
            except User.DoesNotExist:
                return None
        return None

    def _authenticate_user(self, user):
        if user.is_migrated:
            login(self.request, user)
        else:
            self.request.session[UNMIGRATED_AUTH_SESSION_KEY] = user.pk

    def _migrate_account(self, user):
        migrate_account(user)

    def _link_account(self, main_account, to_merge):
        if can_accounts_be_merged(main_account, to_merge):
            sso_type = MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO
            main_account_has_sso = main_account.authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists()
            to_merge_has_sso = to_merge.authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists()

            if main_account_has_sso and to_merge_has_sso:
                raise DRFValidationError(_("Only legacy SSO account can be linked to each AAP account."))

            old_username = to_merge.username
            link_account(main_account, to_merge)

            if self._needs_rename(main_account) and main_account.original_accounts.filter(original_username=old_username).exists():
                main_account.username = old_username
                main_account.save()

    def _needs_rename(self, session_user):
        """
        if the user's username is not among any of the original usernames, request rename
        """
        if session_user.is_migrated:
            return False

        return not session_user.original_accounts.filter(original_username=session_user.username).exists()

    def _is_allowed_to_login(self, token_data, auth_type):
        sso_type = MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO

        if auth_type == "password":
            if token_data["user"].authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists():
                raise DRFValidationError(_("This account has been configured to use SSO and cannot be used with a local username and password."))

        return True
