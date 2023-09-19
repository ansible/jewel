from aap_gateway_api.models import Organization, Team
from aap_gateway_api.serializers import OrganizationSerializer, TeamSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class OrganizationViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer


class OrganizationTeamViewSet(GatewayModelViewSet):
    serializer_class = TeamSerializer

    def get_queryset(self):
        return Team.objects.filter(organization=self.kwargs['pk'])
