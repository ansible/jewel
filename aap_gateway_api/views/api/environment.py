from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import Environment, Organization, Service
from aap_gateway_api.serializers import EnvironmentSerializer, OrganizationSerializer, ServiceSerializer
from aap_gateway_api.views.api.common import GatewayModelViewSet


class EnvironmentViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True)
    def organizations(self, request, pk=None):
        this_object = self.get_object()
        related_objects = Organization.objects.filter(environment=this_object.pk)
        serializer = OrganizationSerializer(related_objects, many=True)
        return Response(serializer.data)

    @action(detail=True)
    def services(self, request, pk=None):
        this_object = self.get_object()
        related_objects = Service.objects.filter(environment=this_object.pk)
        serializer = ServiceSerializer(related_objects, many=True)
        return Response(serializer.data)
