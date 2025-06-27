import json
from typing import Optional

import jwt
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from django.contrib.auth import login
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from aap_gateway_api.models import DefaultServiceType, MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, ServiceCluster, User
from aap_gateway_api.models.user import LegacyAuthType
from aap_gateway_api.serializers.legacy_auth import FinalizeSerializer, LegacyAuthSerializer, UsernamePasswordSerializer
from aap_gateway_api.utils.resources_client import GWResourceAPIClient
from aap_gateway_api.utils.service_token import ValidatedToken, classify_backend, validate_service_token
from aap_gateway_api.utils.user_migration import can_accounts_be_merged, link_account, migrate_account

UNMIGRATED_AUTH_SESSION_KEY = "partially_authed_user"
LOCAL_AUTHENTICATOR = "ansible_base.authentication.authenticator_plugins.local"


UI_SSO_REDIRECT = "/"


class LegacyAuthViewset(viewsets.ViewSet):
    permission_classes = []
    serializer_class = serializers.Serializer

    def list(self, request):
        return self._get_response(request)

    @action(detail=False, methods=["POST"], serializer_class=FinalizeSerializer)
    def finalize(self, request):
        main_account = self._get_user(request)

        if not main_account:
            return self._get_response(request)

        serializer = FinalizeSerializer(data=request.data, context={'needs_rename': self._needs_rename(main_account), 'user': main_account})
        serializer.is_valid(raise_exception=True)

        new_username = serializer.data.get("new_username", None)
        aap_password = serializer.data.get("aap_password", None)

        with transaction.atomic():
            if new_username:
                try:
                    main_account.username = new_username
                    # We're in an atomic block above, so we don't risk uid getting out of sync here.
                    main_account.update_local_authenticator_uid_from_username()
                    main_account.save()
                except IntegrityError:
                    raise DRFValidationError({"new_username": _("%(new_username)s has already been taken.") % {"new_username": new_username}})

            if aap_password:
                local_auth = Authenticator.objects.filter(type=LOCAL_AUTHENTICATOR).first()
                if not local_auth:
                    raise DRFValidationError(
                        {"aap_password": _("This system is not configured to allow local authentication. Please link an external account before finalizing.")}
                    )
                main_account.authenticator_users.all().delete()
                AuthenticatorUser.objects.create(provider=local_auth, uid=main_account.username, user=main_account)
                main_account.set_password(aap_password)
                main_account.save()

            # if the user has an external password account
            if main_account.original_accounts.exclude(backend_classification="local").exclude(backend_classification=None).exists():
                authenticator, created = MigratedAuthenticatorMetadata.objects.get_or_create(
                    type=LegacyAuthType.EXTERNAL_PASSWORD,
                    service=ServiceCluster.get_cluster_by_type(service_type=DefaultServiceType.GATEWAY.value),
                )

                main_account.authenticator_users.all().delete()
                AuthenticatorUser.objects.create(uid=main_account.username, user=main_account, provider=authenticator.authenticator)

            self._migrate_account(main_account)

        self.request.session.flush()
        login(request, main_account)
        return self._get_response(request)

    # NOTE: We enable GET here for the convenience of the UI, so that it can load the CSRF token.
    # Other than that, it doesn't actually do anything.
    @action(detail=False, methods=["POST", "GET"], serializer_class=UsernamePasswordSerializer)
    def controller_password(self, request):
        return self._authenticate_password(request, "controller")

    @action(detail=False, methods=["POST", "GET"], serializer_class=UsernamePasswordSerializer)
    def hub_password(self, request):
        return self._authenticate_password(request, "hub")

    @action(detail=False, methods=["POST", "GET"], serializer_class=UsernamePasswordSerializer)
    def eda_password(self, request):
        return self._authenticate_password(request, "eda")

    def _authenticate_password(self, request, service_type):
        if request.method != "POST":
            return Response()

        serializer = UsernamePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        auth_code = self._check_password(data["username"], data["password"], service_type)
        jwt_token = self._handle_auth_code(auth_code, auth_type="password")

        auth_backend_classification = classify_backend(jwt_token["token_data"]["payload"].get("auth_backend"))

        # If the account is an LDAP account, we'll go ahead and try it on the other service that supports LDAP
        # (either Hub or Controller). If the account is a valid LDAP account here, then we'll automatically
        # link it and set it up to be able to login from the main password endpoint.
        if auth_backend_classification == "ldap":
            uno_reverse_card = {"hub": "controller", "controller": "hub"}
            if service_type in uno_reverse_card:
                try:
                    auth_code = self._check_password(data["username"], data["password"], uno_reverse_card[service_type])
                    # Sonar cloud is gonna yell at this because it's not verifying the signature. That's fine.
                    # We just need to load the auth backend to check that the user is LDAP before we run the
                    # actual token verification.
                    if auth_backend := jwt.decode(auth_code, options={"verify_signature": False}).get("auth_backend"):
                        if classify_backend(auth_backend) == "ldap":
                            self._handle_auth_code(auth_code, auth_type="password")
                except DRFValidationError:
                    pass

        return self._get_response(request)

    @action(detail=False, methods=["GET"])
    def authenticate_sso(self, request):
        auth_code = request.GET.get("auth_code", None)

        try:
            if auth_code is not None:
                self._handle_auth_code(auth_code, auth_type="sso")
        except DRFValidationError as e:
            return redirect(UI_SSO_REDIRECT + f"?auth_failed={json.dumps(e.detail)}")

        return redirect(UI_SSO_REDIRECT)

    @action(detail=False, methods=["POST"])
    def reset(self, request):
        request.session.flush()
        return self._get_response(request)

    def _check_password(self, username, password, service_type) -> str:
        try:
            service = ServiceAPIRoute.objects.get(service_cluster__service_type__name=service_type)
        except ServiceAPIRoute.DoesNotExist:
            raise DRFValidationError(
                {"service_type": _("Service type %(service_type)s does not exist.") % {"service_type": service_type}},
            )

        client = GWResourceAPIClient(
            service=service,
            raise_if_bad_request=False,
        )

        response = client.validate_local_user(username=username, password=password)
        if response.status_code != 200:
            raise DRFValidationError(_("Invalid username or password."))

        return response.json()["auth_code"]

    def _handle_auth_code(self, auth_code, auth_type) -> ValidatedToken:
        # Check that the auth code is valid and load the user.
        try:
            data = validate_service_token(auth_code, required_type="auth_code")
            user = data["user"]
            payload = data["token_data"]["payload"]

            auth_backend_classification = None
            if auth_type == "password":
                auth_backend_classification = classify_backend(payload.get("auth_backend"))

            # add a migration entry for the user
            # This case is supporting reverse-sync.
            # The only other way a service user could be created in Gateway is via migrate_service_data
            # which necessarily creates the MigratedUserMetadata row at the same time. But a reverse-synced
            # user wouldn't have MigratedUserMetadata yet.
            if not user.original_accounts.exists():
                MigratedUserMetadata.objects.create(
                    user=user,
                    service=data["service_cluster"],
                    original_username=payload["username"],
                    backend_classification=auth_backend_classification,
                )

                authenticator_meta = MigratedAuthenticatorMetadata.get_authenticator_for_auth_code(data)

                # Handle cases where UID might be set to None
                uid = payload.get("sso_uid", None)
                if uid is None:
                    uid = user.username
                AuthenticatorUser.objects.create(
                    user=user,
                    provider=authenticator_meta.authenticator,
                    uid=uid,
                )
            else:
                # We already have the migrated user and their metadata, so we just need to update
                # the backend classification if it's a password auth.
                if auth_type == "password":
                    try:
                        migrated_user_metadata = MigratedUserMetadata.objects.get(
                            user=user,
                            service=data["service_cluster"],
                        )
                    except MigratedUserMetadata.DoesNotExist:
                        raise DRFValidationError(
                            _("No migration metadata found for this user/service combination.")
                            + _(" This could mean that this user has already migrated via another service.")
                        )
                    migrated_user_metadata.backend_classification = auth_backend_classification
                    migrated_user_metadata.save(update_fields=["backend_classification"])

            self._is_allowed_to_login(data, auth_type)
        except ValidationError as e:
            raise DRFValidationError(e.message)

        user = data["user"]
        payload = data["token_data"]["payload"]

        session_user = self._get_user(self.request)

        if not session_user:
            self._authenticate_user(user)
        else:
            self._link_account(session_user, user, auth_type, auth_backend_classification)

        return data

    def _get_user(self, request: HttpRequest) -> Optional[User]:
        """Get the current user from request or session.

        Retrieves the authenticated user from the request, or if not present,
        attempts to get a partially authenticated user from the session.

        Args:
            request: The HTTP request object

        Returns:
            User object if found, None otherwise
        """
        if request.user and not isinstance(request.user, AnonymousUser):
            return request.user
        if unmigrated_id := request.session.get(UNMIGRATED_AUTH_SESSION_KEY):
            try:
                return User.objects.get(pk=unmigrated_id)
            except User.DoesNotExist:
                return None
        return None

    def _authenticate_user(self, user: User) -> None:
        """Authenticate a user based on migration status.

        For fully migrated users, performs a full Django login.
        For partially migrated users, stores the user ID in session.

        Args:
            user: The user to authenticate
        """
        if user.is_migrated:
            login(self.request, user)
        else:
            self.request.session[UNMIGRATED_AUTH_SESSION_KEY] = user.pk

    def _migrate_account(self, user: User) -> None:
        """Migrate a user account to fully migrated status.

        Delegates to the migrate_account utility function to handle the
        full migration process for a user account.

        Args:
            user: The user account to migrate
        """
        migrate_account(user)

    def _link_account(self, main_account: User, to_merge: User, auth_type: str, auth_backend_classification: Optional[str]) -> None:
        """Link an external account to the main AAP account.

        Merges a secondary user account into the main account after validating
        that the accounts can be safely merged. Handles SSO restrictions and
        external authentication backend compatibility.

        Args:
            main_account: The primary AAP user account to link to
            to_merge: The secondary user account to be merged
            auth_type: Type of authentication ('password' or 'sso')
            auth_backend_classification: Backend type ('local', 'ldap', etc.) or None

        Raises:
            DRFValidationError: If accounts cannot be merged due to SSO conflicts
                or incompatible external authentication backends
        """
        if can_accounts_be_merged(main_account, to_merge):
            sso_type = MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO
            main_account_has_sso = main_account.authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists()
            to_merge_has_sso = to_merge.authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists()

            if main_account_has_sso and to_merge_has_sso:
                raise DRFValidationError(_("Only one legacy SSO account can be linked to each AAP account."))

            if auth_type == "password" and auth_backend_classification != 'local':
                # > External accounts may be linked to each other as long as they share the same type (LDAP, radius etc.) or to local accounts.
                #
                # So look for any that are not the same type as the one we're trying to link (and not local)
                different_external_accounts = main_account.original_accounts.filter(
                    ~Q(backend_classification=auth_backend_classification) & ~Q(backend_classification='local')
                )

                if different_external_accounts.exists():
                    raise DRFValidationError(
                        _(
                            "External accounts may only be linked to each other if they share the same type "
                            "(LDAP, radius, etc.) or to local accounts. "
                            f"Service Django auth backend: {auth_backend_classification}"
                        )
                    )

            old_username = to_merge.username
            link_account(main_account, to_merge)

            if self._needs_rename(main_account) and main_account.original_accounts.filter(original_username=old_username).exists():
                main_account.username = old_username
                main_account.save()

    def _needs_rename(self, session_user: User) -> bool:
        """Check if user needs to rename their username.

        Determines if the user's current username matches any of their
        original usernames from migrated services.

        Args:
            session_user: The user to check

        Returns:
            True if user needs to rename their username, False otherwise
        """
        if session_user.is_migrated:
            return False

        return not session_user.original_accounts.filter(original_username=session_user.username).exists()

    def _is_allowed_to_login(self, token_data, auth_type):
        sso_type = MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO
        user = token_data["user"]

        if not user.authenticator_users.filter(provider__category="legacy").exists():
            raise DRFValidationError(_("This account is not configured to use legacy authentication."))

        if auth_type == "password":
            if user.authenticator_users.filter(provider__migrated_metadata__type=sso_type).exists():
                raise DRFValidationError(_("This account has been configured to use SSO and cannot be used with a local username and password."))

            # > Once a local account has been linked to an SSO or external account, the user may not use it to authenticate on the gateway.
            auth_backend = token_data["token_data"]["payload"].get("auth_backend")
            if (
                auth_backend is not None
                and classify_backend(auth_backend) == 'local'
                and
                # auth_backend_classification is only set for password legacy auth, so if it exists, we know it's that.
                # So we can just filter out 'local' to see if there's another external account linked to the user.
                token_data["user"].original_accounts.filter(~Q(backend_classification='local') & Q(backend_classification__isnull=False)).exists()
            ):
                raise DRFValidationError(_("This account has been linked to an external account and cannot be used with a local username and password."))

        return True

    def _get_response(self, request):
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
