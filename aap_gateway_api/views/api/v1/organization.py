import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import Organization
from aap_gateway_api.serializers import OrganizationSerializer
from aap_gateway_api.views.api.v1.common import ResourceAPIUpdateMixin, RoleModelViewSet

logger = logging.getLogger('aap.gateway.views.organization')


class OrganizationViewSet(ResourceAPIUpdateMixin, RoleModelViewSet):
    """
    API endpoint that allows organizations to be viewed or edited.
    New comment.
    """

    queryset = Organization.objects.select_related("resource").all()
    serializer_class = OrganizationSerializer
    resource_purpose = "logical collection of users, teams, and resources for organizing access control"

    # Don't allow the deletion of any managed organizations
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.managed:
            logger.info("Managed organizations cannot be deleted.")
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": _("Managed organizations cannot be deleted.")})
        else:
            return super().destroy(request, *args, **kwargs)
