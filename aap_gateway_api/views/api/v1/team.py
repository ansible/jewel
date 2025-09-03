from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import Team
from aap_gateway_api.serializers import TeamSerializer
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import ResourceAPIUpdateMixin, RoleModelViewSet


class TeamViewSet(ResourceAPIUpdateMixin, RoleModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Team.objects.select_related("resource").all()
    serializer_class = TeamSerializer

    def create(self, request, *args, **kwargs):
        # Check if organization management is enabled, but allow superusers to bypass this restriction
        if not get_preference_value('configuration', 'MANAGE_ORGANIZATION_AUTH') and not request.user.is_superuser:
            return Response({"detail": _("Team creation is disabled when MANAGE_ORGANIZATION_AUTH is false.")}, status=status.HTTP_400_BAD_REQUEST)
        return super().create(request, *args, **kwargs)
