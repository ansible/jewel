import logging

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.db import transaction
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.serializers import AuthenticatorUserMoveSerializer, AuthenticatorUserSerializer
from aap_gateway_api.views.api.v1.common import GatewayReadOnlyModelViewSet

# from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class


logger = logging.getLogger('aap.gateway.views.api.v1.authenticator_user')


class AuthenticatorUserViewSet(GatewayReadOnlyModelViewSet):
    """
    API endpoint that allows AuthenticatorUsers to be viewed and listed.
    """

    model = AuthenticatorUser
    queryset = AuthenticatorUser.objects.all()
    serializer_class = AuthenticatorUserSerializer
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]

    @action(detail=True, methods=['post'], serializer_class=AuthenticatorUserMoveSerializer)
    @transaction.atomic
    def move(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        instance = self.get_object()
        old_authenticator = instance.provider
        instance.provider = serializer.validated_data['new_authenticator']
        instance.save()

        if serializer.validated_data['remove_other_authenticators']:
            # Remove all other authenticator_user entries the user has from the old authenticator
            instance.user.authenticator_users.filter(provider=old_authenticator).exclude(pk=instance.pk).delete()

        if not serializer.validated_data['keep_memberships']:
            # Remove the user's existing memberships and let the authenticator map for the
            # new authenticator manage it instead.
            # TODO: Is this doing too much?
            instance.user.role_assignments.all().delete()

        # TODO:
        # plugin = get_authenticator_class(instance.provider.type)(database_instance=instance.provider)
        if serializer.validated_data.get('merge_with_user'):
            new_user = serializer.validated_data['merge_with_user']
            logger.info(f"Merging {new_user} with {instance}")
            # TODO:
            # plugin.move_authenticator_user_to(new_user, instance)
        elif serializer.validated_data.get('merge_accounts_with_same_uid'):
            accounts_with_same_uid = AuthenticatorUser.objects.filter(uid=instance.uid).exclude(pk=instance.pk)
            for account in accounts_with_same_uid:
                logger.info(f"Merging {account} with {instance}")
                # TODO:
                # plugin.move_authenticator_user_to(account.user, instance)

        response = AuthenticatorUserViewSet.serializer_class(instance).data
        return Response(response)
