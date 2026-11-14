from drf_spectacular.utils import extend_schema
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryResponse
from google.protobuf.json_format import MessageToDict
from rest_framework.response import Response
from rest_framework.views import APIView

from aap_gateway_api.utils.xds_resources import collect_clusters, collect_listeners, collect_secrets

# ---------------------------------------------------------------------------
# Envoy xDS REST control plane views
#
# These views implement the Envoy REST-JSON variant of the xDS discovery
# protocol.  Envoy POSTs a DiscoveryRequest and expects a DiscoveryResponse
# back.  There are three resource types served here:
#
#   CDS (Cluster Discovery Service)  - upstream cluster definitions
#   LDS (Listener Discovery Service) - listener + filter-chain definitions
#   SDS (Secret Discovery Service)   - TLS certificates / CA bundles
#
# None of these endpoints require authentication because they are only
# reachable from Envoy on the loopback interface.
#
# DEPRECATED: these REST endpoints are superseded by the gRPC ADS control
# plane (aap_gateway_api/proxy/ads.py), which is the primary xDS transport.  They
# remain functional as a rollback/compatibility path, and every response
# carries a `Deprecation: true` header.
#
# The resource collection itself (queries, protobuf packing, caching) lives
# in aap_gateway_api/utils/xds_resources.py and is shared with the gRPC ADS
# control plane.  Responses are cached and invalidated by model signals (see
# aap_gateway_api/signals/xds_cache.py) so that the ~5-second Envoy
# polling interval does not trigger full DB rebuilds every time.
# ---------------------------------------------------------------------------


class XDSDeprecationMixin:
    """Marks every response from a REST xDS view with a `Deprecation` header."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        return response


@extend_schema(exclude=True)
class XDSView(XDSDeprecationMixin, APIView):
    """Base for the deprecated REST xDS views; superseded by gRPC ADS."""

    authentication_classes = []
    permission_classes = []

    def get_resource_names(self, request):
        # Parse resource_names from the POST body, preserving the semantics of
        # the filtering the views historically applied to their querysets:
        # a missing value means all resources, a lone "*" also means all.
        names = request.POST.get("resource_names")
        if not names:
            return None
        if len(names) == 1 and names[0] == "*":
            return None
        # request.POST may yield a bare string (form-encoded body); listing it
        # keeps the historical name__in filtering behavior for that case.
        return list(names)

    def get_xds_response(self, resource_set):
        """Wrap a ResourceSet into a protobuf DiscoveryResponse."""
        response = DiscoveryResponse(version_info=resource_set.version, resources=resource_set.resources)
        return MessageToDict(response)


@extend_schema(exclude=True)
class ClusterDiscoverServiceView(XDSView):
    """CDS -- returns an Envoy Cluster definition for every Route.

    Deprecated: superseded by gRPC ADS. Kept as a rollback path.
    """

    def post(self, request, format=None):
        return Response(self.get_xds_response(collect_clusters(self.get_resource_names(request))))


@extend_schema(exclude=True)
class ListenerDiscoverServiceView(XDSView):
    """LDS -- returns an Envoy Listener for every HTTPPort.

    Deprecated: superseded by gRPC ADS. Kept as a rollback path.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        return Response(self.get_xds_response(collect_listeners(self.get_resource_names(request))))


@extend_schema(exclude=True)
class SecretDiscoverServiceView(XDSView):
    """SDS -- returns a single Secret containing all trusted CA certificates.

    Deprecated: superseded by gRPC ADS. Kept as a rollback path.
    """

    # No authentication by design -- only reachable from Envoy on loopback.
    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        return Response(self.get_xds_response(collect_secrets()))
