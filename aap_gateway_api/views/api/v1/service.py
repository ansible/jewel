from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode
from aap_gateway_api.serializers import (
    AdditionalRouteSerializer,
    HTTPPortSerializer,
    ServiceAPIRouteSerializer,
    ServiceClusterSerializer,
    ServiceNodeSerializer,
)
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ProxyUnsafeGatewayModelViewSet


class ServiceAPIRouteViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = ServiceAPIRoute.objects.all()
    serializer_class = ServiceAPIRouteSerializer

    def object_write_unsafe(self, request, obj: ServiceAPIRoute) -> bool:
        # Currently we can be sure that there will only be one server per type,
        # so we do not have to check if there are any more services of type GATEWAY
        return obj.service_cluster.service_type in ServiceCluster.ServiceType.GATEWAY


class ServiceNodeViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = ServiceNode.objects.all()
    serializer_class = ServiceNodeSerializer

    def object_write_unsafe(self, request, obj: ServiceNode) -> bool:
        # Currently we can be sure that there will only be one server per type,
        # so we do not have to check if there are any more services of type GATEWAY
        return obj.service_cluster.service_type in ServiceCluster.ServiceType.GATEWAY


class HTTPPortViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = HTTPPort.objects.all()
    serializer_class = HTTPPortSerializer

    def object_write_unsafe(self, request, obj: HTTPPort) -> bool:
        # reject all requests to modify the API port
        return bool(obj.is_api_port)


class ServiceClusterViewSet(ProxyUnsafeGatewayModelViewSet):
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
