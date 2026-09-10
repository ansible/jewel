from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.renderers import BrowsableAPIRenderer, JSONRenderer
from rest_framework.response import Response

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.serializers import ServiceKeySerializerRead, ServiceKeySerializerWrite
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet

deprecation_message = (
    "Notice: the POST method has been removed from this endpoint. "
    "Attempting to create a service_key from this endpoint will result in "
    "an HTTP 405. Please consult the documentation on how to properly "
    "create service keys. Passing service_cluster, secret, secret_length, "
    "mark_previous_inactive, and algorithm to PUT or PATCH will be silently ignored."
)


# This creates an API Renderer that will not show the HTML/Raw input forms for the POST method
class ServiceKeyBrowsableAPIRenderer(BrowsableAPIRenderer):
    def show_form_for_method(self, view, method, request, obj):
        if method.upper() == "POST":
            return False
        return super().show_form_for_method(view, method, request, obj)


@extend_schema(
    deprecated=True,
    request=ServiceKeySerializerWrite,
    responses=ServiceKeySerializerRead,
)
class ServiceKeyViewSet(GatewayModelViewSet):
    """
    API endpoint that allows configuring service authentication keys.
    """

    permission_classes = (
        OAuth2ScopePermission,
        IsSuperuserOrAuditor,
    )
    queryset = ServiceKey.objects.all()
    serializer_class = ServiceKeySerializerRead
    deprecated = True
    # The red banner message in the browsable API
    deprecated_message = deprecation_message
    # The message for the HTTP warning header which defaults to the "this whole endpoint is deprecated"
    deprecation_warning_header_override = "HTTP POST method is no longer supported for this endpoint."
    # Turn off the HTML/raw input forms for the POST method
    renderer_classes = (
        JSONRenderer,
        ServiceKeyBrowsableAPIRenderer,
    )

    def create(self, request, *args, **kwargs):
        resp_data = {
            "detail": (
                "For security reasons, creating service keys through this API is no longer supported. "
                "To create a key for a registered service, run "
                "`aap-gateway-manage generate_service_secret <service_cluster_name>` in the Gateway environment."
            ),
        }

        return Response(resp_data, status=status.HTTP_405_METHOD_NOT_ALLOWED)
