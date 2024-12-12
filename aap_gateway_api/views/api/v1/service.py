from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import AdditionalRoute, DefaultServiceType, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.serializers import (
    AdditionalRouteSerializer,
    HTTPPortSerializer,
    ServiceAPIRouteSerializer,
    ServiceClusterSerializer,
    ServiceNodeSerializer,
    ServiceTypeSerializer,
)
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ProxyUnsafeGatewayModelViewSet


class ServiceAPIRouteViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows service API routes to be viewed or edited.
    """

    queryset = ServiceAPIRoute.objects.all()
    serializer_class = ServiceAPIRouteSerializer

    def object_write_unsafe(self, request, obj: ServiceAPIRoute) -> bool:
        # Currently we can be sure that there will only be one server per type,
        # so we do not have to check if there are any more services of type GATEWAY
        return obj.service_cluster.service_type.name in [DefaultServiceType.GATEWAY]


class ServiceNodeViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows service nodes to be viewed or edited.
    """

    queryset = ServiceNode.objects.all()
    serializer_class = ServiceNodeSerializer

    def object_write_unsafe(self, request, obj: ServiceNode) -> bool:
        # Currently we can be sure that there will only be one server per type,
        # so we do not have to check if there are any more services of type GATEWAY
        return obj.service_cluster.service_type.name in [DefaultServiceType.GATEWAY]


class HTTPPortViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows HTTP ports to be viewed or edited.
    """

    queryset = HTTPPort.objects.all()
    serializer_class = HTTPPortSerializer

    def object_write_unsafe(self, request, obj: HTTPPort) -> bool:
        # reject all requests to modify the API port
        return bool(obj.is_api_port)

    def destroy(self, request, pk=None):
        instance = self.get_object()

        # The API port cannot be deleted
        if instance.is_api_port:
            return Response({'detail': _('Cannot delete the API port')}, status=status.HTTP_403_FORBIDDEN)

        return super().destroy(instance)


class ServiceClusterViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows service clusters to be viewed or edited.
    """

    queryset = ServiceCluster.objects.all()
    serializer_class = ServiceClusterSerializer


class ServiceTypeViewSet(ProxyUnsafeGatewayModelViewSet):
    """
    API endpoint that allows service types to be viewed or edited
    """

    queryset = ServiceType.objects.all()
    serializer_class = ServiceTypeSerializer


class AdditionalRouteViewSet(GatewayModelViewSet):
    """
    API endpoint that allows additional routes to be viewed or edited.
    """

    queryset = AdditionalRoute.objects.all()
    serializer_class = AdditionalRouteSerializer
