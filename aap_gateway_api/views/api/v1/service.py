from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode
from aap_gateway_api.serializers import (
    AdditionalRouteSerializer,
    HTTPPortSerializer,
    ServiceAPIRouteSerializer,
    ServiceClusterSerializer,
    ServiceNodeSerializer,
)
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class ServiceAPIRouteViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = ServiceAPIRoute.objects.all()
    serializer_class = ServiceAPIRouteSerializer


class ServiceNodeViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = ServiceNode.objects.all()
    serializer_class = ServiceNodeSerializer


class HTTPPortViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = HTTPPort.objects.all()
    serializer_class = HTTPPortSerializer


class ServiceClusterViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = ServiceCluster.objects.all()
    serializer_class = ServiceClusterSerializer


class AdditionalRouteViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = AdditionalRoute.objects.all()
    serializer_class = AdditionalRouteSerializer
