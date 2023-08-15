from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import Organization, Team
from aap_gateway_api.serializers import OrganizationSerializer, TeamSerializer
from aap_gateway_api.views.api.common import GatewayModelViewSet


class OrganizationViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True)
    def teams(self, request, pk=None):
        organization = self.get_object()
        teams = Team.objects.filter(organization=organization.id)
        serializer = TeamSerializer(teams, many=True)
        return Response(serializer.data)
