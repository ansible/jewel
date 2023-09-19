from aap_gateway_api.models import Environment, Organization, Service
from aap_gateway_api.serializers import EnvironmentSerializer, OrganizationSerializer, ServiceSerializer
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


class EnvironmentServiceViewSet(GatewayModelViewSet):
    serializer_class = ServiceSerializer

    def get_queryset(self):
        return Service.objects.filter(environment=self.kwargs['pk'])
