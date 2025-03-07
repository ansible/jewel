import logging

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.oauth2_provider.models import OAuth2Application
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from aap_gateway_api.serializers import AppUrlSerializer

logger = logging.getLogger('aap.gateway.views.api.v1.app_url')


class AppUrlViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows oauth apps to be listed for name and app_url
    """

    queryset = None
    serializer_class = AppUrlSerializer
    permission_classes = [AnsibleBaseUserPermissions, OAuth2ScopePermission]

    def get_queryset(self):
        request = self.request
        query = ~Q(app_url='') & Q(app_url__isnull=False)

        # Auditor role should see all of the app_urls from OAuthApplication
        if request.user.is_platform_auditor:
            logger.debug("Platform Auditor detected, obtaining all valid OAuth2Applications with 'app_url'.")
        else:
            # Therefore if we do not have an auditor we need to add the organization filter to the query
            logger.debug("Platform Auditor NOT detected, obtaining valid OAuth2Applications with 'app_url' related to the current user's orgs.")
            query = query & Q(organization__in=request.user.organizations)

        return OAuth2Application.objects.filter(query).order_by('id')

    # We don't want anyone loading the application from the app_urls endpoint singularly
    # This annotation hides the detail endpoint app_urls/x/ from openapi docs
    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        logger.info("OAuth2Applications can not be individually queried against from this API endpoint.")
        return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": _("Use the applications api endpoint instead.")})
