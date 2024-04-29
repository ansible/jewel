from aap_gateway_api.models import Organization
from aap_gateway_api.serializers import OrganizationSerializer
from aap_gateway_api.views.api.v1.common import ResourceAPIUpdateMixin, RoleModelViewSet


class OrganizationViewSet(ResourceAPIUpdateMixin, RoleModelViewSet):
    """
    API endpoint that allows organizations to be viewed or edited.
    """

    queryset = Organization.objects.select_related("resource").all()
    serializer_class = OrganizationSerializer
