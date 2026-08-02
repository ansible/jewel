import logging

from django.db import IntegrityError
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
    """

    queryset = Organization.objects.select_related("resource").all()
    serializer_class = OrganizationSerializer
    resource_purpose = "logical collection of users, teams, and resources for organizing access control"

    def create(self, request, *args, **kwargs):
        """Override create to handle race conditions with SSO/LDAP auto-created organizations.

        When an external identity provider (LDAP, SAML, etc.) is configured with
        create_objects=True, organizations may be auto-created during user login.
        If a user then tries to create the same organization via the API, a race
        condition can cause an IntegrityError on the unique name constraint. This
        override catches that error and returns the existing organization instead
        of surfacing a confusing error to the user.
        """
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            # The org was created concurrently (e.g. by SSO auto-provisioning).
            # Look up the existing org by name and return it.
            org_name = request.data.get('name')
            if org_name is None:
                raise

            try:
                existing_org = Organization.objects.get(name=org_name)
            except Organization.DoesNotExist:
                # IntegrityError was not caused by a name conflict; re-raise.
                raise IntegrityError

            logger.info(
                "Organization '%s' was concurrently created (likely by SSO auto-provisioning). Returning the existing organization.",
                org_name,
            )
            serializer = self.get_serializer(existing_org)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # Don't allow the deletion of any managed organizations
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.managed:
            logger.info("Managed organizations cannot be deleted.")
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": _("Managed organizations cannot be deleted.")})
        else:
            return super().destroy(request, *args, **kwargs)
