from aap_gateway_api.models import Environment
from aap_gateway_api.serializers import EnvironmentSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class EnvironmentViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer
