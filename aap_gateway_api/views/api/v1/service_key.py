from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.renderers import BrowsableAPIRenderer, JSONRenderer
from rest_framework.response import Response

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.serializers import ServiceKeySerializerRead, ServiceKeySerializerWrite
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet

# Keep POST routable so drf-spectacular discovers the operation and can mark it deprecated.
# The view still rejects POST requests with a custom 405 response, while the code below removes
# POST from the browsable API, OPTIONS metadata, and advertised Allow headers.

POST_DEPRECATION_MESSAGE = (
    "Notice: the POST method has been removed from this endpoint. "
    "Attempting to create a service_key from this endpoint will result in "
    "an HTTP 405. Please consult the documentation on how to properly "
    "create service keys."
)

UPDATE_DEPRECATION_MESSAGE = (
    "<b>Notice: The following fields are deprecated for PUT/PATCH requests and will be silently ignored:</b><br>"
    " <ul>"
    "    <li><b>service_cluster:</b> Service keys cannot be moved between service clusters. Generate a new key for the target service cluster.</li>"
    "    <li><b>secret:</b> This value is generated and cannot be edited.</li>"
    "    <li><b>secret_length:</b> This applies only when generating a key.</li>"
    "    <li><b>mark_previous_inactive:</b> This applies only when generating a key.</li>"
    "    <li><b>algorithm:</b> Changing the algorithm without regenerating the secret would invalidate the key.</li>"
    " </ul>"
)


# This renderer suppresses the POST HTML/Raw input form in the browsable API.
class ServiceKeyBrowsableAPIRenderer(BrowsableAPIRenderer):
    """Suppress the browsable API input form for POST requests."""

    def show_form_for_method(self, view, method, request, obj):
        if method.upper() == "POST":
            return False
        return super().show_form_for_method(view, method, request, obj)


@extend_schema_view(
    # Document POST as deprecated with the legacy request schema and current response schema.
    create=extend_schema(
        deprecated=True,
        request=ServiceKeySerializerWrite,
        responses=ServiceKeySerializerRead,
    ),
    # Document legacy create-only fields in PUT/PATCH request schemas as deprecated.
    update=extend_schema(request=ServiceKeySerializerWrite),
    partial_update=extend_schema(request=ServiceKeySerializerWrite),
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
    # The message for the HTTP warning header on the collection route.
    deprecation_warning_header_override = "HTTP POST method is no longer supported for this endpoint."
    # Turn off the HTML/raw input forms for the POST method
    renderer_classes = (
        JSONRenderer,
        ServiceKeyBrowsableAPIRenderer,
    )

    @property
    def is_detail_route(self):
        """Determine whether the request targets a single service key."""
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        return lookup_url_kwarg in getattr(self, "kwargs", {})

    @property
    def deprecated_message(self):
        """Select the browsable API notice for the collection or detail route."""
        if self.is_detail_route:
            return UPDATE_DEPRECATION_MESSAGE
        return POST_DEPRECATION_MESSAGE

    @property
    def deprecated_message_html_safe(self):
        if self.is_detail_route:
            return True
        return False

    def finalize_response(self, request, response, *args, **kwargs):
        """Remove POST from the advertised Allow header."""
        response = super().finalize_response(request, response, *args, **kwargs)
        if self.is_detail_route and "Warning" in response:
            del response["Warning"]
        if "Allow" in response:
            response["Allow"] = ", ".join(method for method in response["Allow"].split(", ") if method != "POST")
        return response

    def options(self, request, *args, **kwargs):
        """Remove POST from OPTIONS action metadata."""
        response = super().options(request, *args, **kwargs)
        response.data.get("actions", {}).pop("POST", None)
        return response

    def create(self, request, *args, **kwargs):
        # Return the custom 405 response for attempted POST requests.
        resp_data = {
            "detail": (
                "For security reasons, creating service keys through this API is no longer supported. "
                "To create a key for a registered service, run "
                "`aap-gateway-manage generate_service_secret <service_cluster_name>` in the Gateway environment."
            ),
        }

        return Response(resp_data, status=status.HTTP_405_METHOD_NOT_ALLOWED)
