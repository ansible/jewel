from rest_framework import permissions

from aap_gateway_api.models import Service
from aap_gateway_api.serializers import ServiceSerializer
from aap_gateway_api.views.api.common import GatewayModelViewSet


class ServiceViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]
