from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.policies import visible_users
from django.http import Http404

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.serializers import OrganizationSerializer, TeamSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin


class UserTeamViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    model = Team
    serializer_class = TeamSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return Team.access_qs(user, 'member')
        except User.DoesNotExist:
            raise Http404("No User matches the given query")


class UserOrganizationViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    model = Organization
    serializer_class = OrganizationSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return Organization.access_qs(user, 'member')
        except User.DoesNotExist:
            raise Http404("No User matches the given query")
