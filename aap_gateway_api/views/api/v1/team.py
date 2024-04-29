from aap_gateway_api.models import Team
from aap_gateway_api.serializers import TeamSerializer
from aap_gateway_api.views.api.v1.common import ResourceAPIUpdateMixin, RoleModelViewSet


class TeamViewSet(ResourceAPIUpdateMixin, RoleModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Team.objects.select_related("resource").all()
    serializer_class = TeamSerializer
