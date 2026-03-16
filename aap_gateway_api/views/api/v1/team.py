from ansible_base.rbac.policies import can_view_all_users

from aap_gateway_api.models import Team
from aap_gateway_api.serializers import TeamSerializer
from aap_gateway_api.utils.rbac import visible_teams
from aap_gateway_api.utils.views.permissions import IsSuperuserOrManageOrgsEnabled
from aap_gateway_api.views.api.v1.common import ResourceAPIUpdateMixin, RoleModelViewSet


class TeamViewSet(ResourceAPIUpdateMixin, RoleModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    resource_purpose = "organization subdivisions that group users for bulk permission assignment and role-based access control"

    queryset = Team.objects.select_related("resource").all()
    serializer_class = TeamSerializer
    permission_classes = RoleModelViewSet.permission_classes + [IsSuperuserOrManageOrgsEnabled]

    # Enables ORG_ADMINS_CAN_SEE_ALL_USERS to see all teams as well
    def filter_queryset(self, qs):
        if can_view_all_users(self.request.user):
            qs = visible_teams(self.request.user, queryset=qs)
            # Skip RoleModelViewSet's access_qs so visible_teams result is kept;
            # still run DRF filter chain (ordering, search, pagination, etc.)
            return super(RoleModelViewSet, self).filter_queryset(qs)
        return super().filter_queryset(qs)
