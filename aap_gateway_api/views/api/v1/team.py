from rest_framework import permissions

from aap_gateway_api.models import Team
from aap_gateway_api.serializers import TeamSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class TeamViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
