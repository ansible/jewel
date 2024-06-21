from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.views import DABOAuth2UserViewsetMixin
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.policies import visible_users
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import User
from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin


class UserViewSet(DABOAuth2UserViewsetMixin, ResourceAPIUpdateMixin, GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    model = User
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        return super().filter_queryset(qs)

    @action(detail=True, methods=["get"], url_name="authenticators-list")
    def authenticators(self, request, pk=None):
        # first, check if the current user has permission to view authenticators
        permission_class = IsSuperuserOrAuditor()
        if not permission_class.has_permission(request, None):
            return Response(status=403)
        try:
            user = visible_users(self.request.user).get(pk=pk)
        except User.DoesNotExist:
            return Response(status=404)
        queryset = Authenticator.objects.filter(authenticator_providers__user=user)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = AuthenticatorSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        data = AuthenticatorSerializer(queryset, many=True).data
        return Response(data)


class DeprecatedRelatedUserViewSet(UserViewSet):
    """
    Shows all users for sublists like /api/v1/organizations/5/users/
    the related view still checks organization view permission
    """

    deprecated = True
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    # Methods for compatibility with the old users and admins endpoints
    def get_association_role_definition(self):
        parent_model_name = self.parent_viewset.serializer_class.Meta.model._meta.model_name.title()
        if self.association_fk == 'users':
            role_name = f'{parent_model_name} Member'
        elif self.association_fk == 'admins':
            role_name = f'{parent_model_name} Admin'
        return RoleDefinition.objects.get(name=role_name)

    def get_sublist_queryset(self, parent_instance):
        rd = self.get_association_role_definition()
        object_roles = rd.object_roles.filter(object_id=parent_instance.pk)
        return self.queryset.filter(has_roles__in=object_roles)

    def perform_associate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition()
        for user in related_instances:
            rd.give_permission(user, parent_instance)

    def perform_disassociate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition()
        for user in related_instances:
            rd.remove_permission(user, parent_instance)
