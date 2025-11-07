from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.policies import visible_users
from django.db.models.functions import Cast
from django.http import Http404
from drf_spectacular.utils import extend_schema

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.serializers import OrganizationSerializer, TeamSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin


@extend_schema(
    deprecated=True,
)
class UserTeamViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    model = Team
    serializer_class = TeamSerializer
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return Team.access_qs(user, 'member')
        except User.DoesNotExist:
            raise Http404("No User matches the given query")


@extend_schema(
    deprecated=True,
)
class UserOrganizationViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    model = Organization
    serializer_class = OrganizationSerializer
    permission_classes = [OAuth2ScopePermission, AnsibleBaseUserPermissions]

    def get_queryset(self):
        try:
            user = visible_users(self.request.user).get(pk=self.kwargs['pk'])
            return Organization.objects.filter(
                id__in=ObjectRole.objects.filter(
                    role_definition__name__in=(Organization.member_rd_name, Organization.admin_rd_name), users=user.id
                ).values_list(Cast('object_id', output_field=Organization._meta.pk))
            )
        except User.DoesNotExist:
            raise Http404("No User matches the given query")
