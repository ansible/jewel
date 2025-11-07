from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.oauth2_provider.views import DABOAuth2UserViewsetMixin
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.policies import can_view_all_users, visible_users
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import User
from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin


@extend_schema(responses=UserSerializer)
class UserViewSet(DABOAuth2UserViewsetMixin, ResourceAPIUpdateMixin, GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    model = User
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        return super().filter_queryset(qs)

    def get_queryset(self):
        if self.detail:
            return User.all_objects.select_related("resource").all()
        return super().get_queryset()

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


@extend_schema(
    deprecated=True,
)
class DeprecatedRelatedUserViewSet(DABOAuth2UserViewsetMixin, GatewayModelViewSet):
    """
    Shows all users for sublists like /api/v1/organizations/5/users/
    the related view still checks organization view permission
    """

    model = User
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]

    # Methods for compatibility with the old users and admins endpoints
    def get_association_role_definition(self, parent_instance):
        rd = None
        if self.association_fk == 'users':
            rd = parent_instance.member_rd
        elif self.association_fk == 'admins':
            rd = parent_instance.admin_rd
        return rd

    def get_sublist_queryset(self, parent_instance):
        rd = self.get_association_role_definition(parent_instance)
        object_roles = rd.object_roles.filter(object_id=parent_instance.pk)
        return self.queryset.filter(has_roles__in=object_roles)

    def perform_associate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition(parent_instance)
        for user in related_instances:
            rd.give_permission(user, parent_instance)

    def perform_disassociate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition(parent_instance)
        for user in related_instances:
            rd.remove_permission(user, parent_instance)

    def filter_associate_queryset(self, qs):
        """
        Filter user queryset for association operations (ADD operations).
        Hybrid approach: Org admins can only ADD users they can see (security-first),
        but can view and REMOVE existing associations even for users they can't normally see.
        """
        qs = visible_users(self.request.user, queryset=qs, always_show_superusers=False, always_show_self=False)
        return super().filter_queryset(qs)


class OrganizationRelatedUserViewSet(DeprecatedRelatedUserViewSet):
    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs, always_show_superusers=False, always_show_self=False)
        return super().filter_queryset(qs)

    def get_sublist_queryset(self, parent_instance):
        """
        For listing existing associations and providing candidates for disassociation.
        Hybrid approach: Org admins can see ALL existing associations (functional approach)
        even if they can't normally see those users, so they can manage existing memberships.
        """
        # Get the base queryset of associated users
        queryset = super().get_sublist_queryset(parent_instance)

        # Apply visibility filtering - visible_users already handles can_view_all_users internally
        # Note: We don't use always_show_self=True here because we only want to show users
        # that are actually part of the association, not the requesting user if they're not
        return visible_users(self.request.user, queryset=queryset, always_show_superusers=False, always_show_self=False)


class TeamRelatedUserViewSet(DeprecatedRelatedUserViewSet):
    def is_team_admin(self, parent_instance):
        return self.request.user.has_obj_perm(parent_instance, 'change')

    def get_sublist_queryset(self, parent_instance):
        """
        For listing existing associations and providing candidates for disassociation.
        Hybrid approach: Org admins and team admins can see ALL existing associations (functional approach)
        even if they can't normally see those users, so they can manage existing memberships.
        """
        queryset = super().get_sublist_queryset(parent_instance)

        # If user can view all users (including org admins when ORG_ADMINS_CAN_SEE_ALL_USERS=True)
        # or is a team admin, show all existing associations for management purposes
        if can_view_all_users(self.request.user) or self.is_team_admin(parent_instance):
            return queryset
        return queryset.filter(pk=self.request.user.id)
