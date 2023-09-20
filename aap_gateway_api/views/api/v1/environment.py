from aap_gateway_api.models import Environment, Organization
from aap_gateway_api.serializers import EnvironmentSerializer, OrganizationSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class EnvironmentViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer


class EnvironmentOrganizationViewSet(GatewayModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.filter(environment=self.kwargs['pk'])
