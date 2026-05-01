import logging

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from aap_gateway_api.serializers import AuthenticatorUserMoveSerializer, AuthenticatorUserSerializer
from aap_gateway_api.views.api.v1.common import GatewayReadOnlyModelViewSet

logger = logging.getLogger('aap.gateway.views.api.v1.authenticator_user')


class AuthenticatorUserViewSet(GatewayReadOnlyModelViewSet):
    """
    API endpoint that allows AuthenticatorUsers to be viewed and listed.
    """

    model = AuthenticatorUser
    queryset = AuthenticatorUser.objects.all().order_by('id')
    serializer_class = AuthenticatorUserSerializer
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]

    @extend_schema(
        request=AuthenticatorUserMoveSerializer,
        responses={200: AuthenticatorUserSerializer},
    )
    @action(detail=True, methods=['post'], serializer_class=AuthenticatorUserMoveSerializer)
    @transaction.atomic
    def move(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        instance = self.get_object()
        old_authenticator = instance.provider
        new_authenticator = serializer.validated_data['new_authenticator']
        original_uid = instance.uid

        if serializer.validated_data['remove_other_authenticators']:
            # Remove all other authenticator_user entries the user has from the old authenticator
            instance.user.authenticator_users.filter(provider=old_authenticator).exclude(pk=instance.pk).delete()

        if not serializer.validated_data['keep_memberships']:
            # Remove the user's existing memberships and let the authenticator map for the
            # new authenticator manage it instead.
            # TODO: Is this doing too much?
            instance.user.role_assignments.all().delete()

        plugin = get_authenticator_class(instance.provider.type)(database_instance=instance.provider)
        if serializer.validated_data.get('merge_with_user'):
            new_user = serializer.validated_data['merge_with_user']
            if new_user.pk == instance.user.pk:
                raise ValidationError({"merge_with_user": _("Cannot merge user with themselves.")})
            logger.info(f"Merging {new_user} with {instance}")
            plugin.move_authenticator_user_to(new_user, instance)
        else:
            try:
                account_with_same_uid = AuthenticatorUser.objects.get(uid=instance.uid, provider=new_authenticator)
                new_user = account_with_same_uid.user
                if serializer.validated_data.get('merge_accounts_with_same_uid'):
                    if new_user.pk == instance.user.pk:
                        raise ValidationError({"merge_accounts_with_same_uid": _("User has already been merged with user {}.").format(instance.user.username)})
                    plugin.move_authenticator_user_to(new_user, instance)
                else:
                    raise ValidationError(
                        _("Cannot move user to %(authenticator)s. A user with a uid of %(uid)s already exists for this authenticator.")
                        % {"authenticator": new_authenticator.name, "uid": instance.uid}
                    )
            except AuthenticatorUser.DoesNotExist:
                new_user = instance.user
                new_user.save()
                instance.provider = new_authenticator
                instance.save()

        new_user.save()

        try:
            new_authenticator_user = AuthenticatorUser.objects.get(user=new_user, provider=new_authenticator)
        except AuthenticatorUser.DoesNotExist:
            new_authenticator_user = AuthenticatorUser.objects.create(user=new_user, uid=original_uid, provider=new_authenticator)

        if new_uid := serializer.validated_data.get('new_uid'):
            new_authenticator_user.uid = new_uid
            new_authenticator_user.save()

        response = AuthenticatorUserViewSet.serializer_class(new_authenticator_user).data
        return Response(response)
