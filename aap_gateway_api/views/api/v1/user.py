from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.lib.utils.models import is_system_user
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.oauth2_provider.views import DABOAuth2UserViewsetMixin
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.models import RoleUserAssignment
from ansible_base.rbac.policies import can_view_all_users, visible_users
from django.db.models import Exists, OuterRef, Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from aap_gateway_api.models import User
from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.utils.rbac import get_platform_auditor_role
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin

# Single source of truth for the user queryset prefetch chain used by all user viewsets.
# Adding provider via select_related prevents N+1 when serializer reads authentication.provider.
PREFETCH_AUTHENTICATOR_USERS = Prefetch(
    'authenticator_users',
    queryset=AuthenticatorUser.objects.select_related('provider'),
)


@extend_schema(responses=UserSerializer)
class UserViewSet(DABOAuth2UserViewsetMixin, ResourceAPIUpdateMixin, GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    resource_purpose = "authenticated platform users with permissions assigned directly or via team membership"

    model = User
    queryset = (
        User.objects.select_related("resource", "last_login_from")
        .prefetch_related(PREFETCH_AUTHENTICATOR_USERS)
        .all()
    )
    serializer_class = UserSerializer
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]

    def perform_destroy(self, instance):
        if is_system_user(instance):
            raise ValidationError({"detail": "The system user cannot be deleted"})
        super().perform_destroy(instance)

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        return super().filter_queryset(qs)

    def get_queryset(self):
        if self.detail:
            return (
                User.all_objects.select_related("resource", "last_login_from")
                .prefetch_related(PREFETCH_AUTHENTICATOR_USERS)
                .all()
            )
        qs = super().get_queryset()
        # Note: get_platform_auditor_role() does a DB lookup per call (ManagedRoleManager
        # cache is not populated). Single query, negligible vs the N+1 queries eliminated.
        rd = get_platform_auditor_role()
        # Optimize list queries to avoid N+1 per-object queries during serialization:
        # - select_related: prevents lazy-loading FK objects in get_summary_fields()
        #   (adds self-referential JOINs; may affect query plans on very large user tables)
        # - annotate: computes is_platform_auditor in a single subquery instead of
        #   one .exists() call per user object
        return qs.select_related("modified_by", "created_by", "last_login_from").annotate(
            _annotated_is_platform_auditor=Exists(
                RoleUserAssignment.objects.filter(
                    user_id=OuterRef("pk"),
                    role_definition=rd,
                )
            ),
        )

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

    deprecated_message = "This endpoint is deprecated and will be removed in a future release. Use /api/gateway/v1/role_user_assignments/ instead."

    model = User
    queryset = (
        User.objects.select_related("resource", "last_login_from")
        .prefetch_related(PREFETCH_AUTHENTICATOR_USERS)
        .all()
    )
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
