from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import Team, User
from aap_gateway_api.serializers import TeamSerializer, UserSerializer
from aap_gateway_api.views.api.common import GatewayModelViewSet


class UserViewSet(GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer

    @action(detail=True)
    def teams(self, request, pk=None):
        user = self.get_object()
        teams = Team.objects.filter(users__username=user.username)
        serializer = TeamSerializer(teams, many=True)
        return Response(serializer.data)
