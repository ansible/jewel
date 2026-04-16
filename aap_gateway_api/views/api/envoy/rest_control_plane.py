from django.db.models import Max
from envoy.config.cluster.v3.cluster_pb2 import Cluster
from envoy.config.listener.v3.listener_pb2 import Listener
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryResponse
from google.protobuf import symbol_database
from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import MessageToDict, ParseDict
from rest_framework.response import Response
from rest_framework.views import APIView

from aap_gateway_api.models import HTTPPort, Route
from aap_gateway_api.models.service_cluster import ServiceCluster

# These modules must be imported so their protobuf message types get registered
# with symbol_database.Default().pool.  Without this, ParseDict() will fail to
# resolve the @type URLs embedded in the xDS resources Envoy expects.
# isort: off
from envoy.extensions.transport_sockets.tls.v3 import tls_pb2  # noqa: F401
from envoy.extensions.filters.http.router.v3 import router_pb2  # noqa: F401
from envoy.extensions.filters.http.lua.v3 import lua_pb2  # noqa: F401
from envoy.extensions.access_loggers.stream.v3 import stream_pb2  # noqa: F401
from envoy.extensions.filters.http.ext_authz.v3 import ext_authz_pb2  # noqa: F401
from envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2  # noqa: F401
from envoy.service.secret.v3 import sds_pb2, sds_pb2_grpc  # noqa: F401
from envoy.extensions.transport_sockets.tls.v3.secret_pb2 import Secret
from aap_gateway_api.models.ca_certificate import CACertificate
from aap_gateway_api.utils.xds_configs import SDS_SECRET_CONFIG_NAME
from drf_spectacular.utils import extend_schema

# isort: on


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
# ---------------------------------------------------------------------------


@extend_schema(exclude=True)
class XDSView(APIView):
    authentication_classes = []
    permission_classes = []

    def get_qs(self, request, ModelClass, name_field):
        # DISTINCT ON is PostgreSQL-specific; it gives us one row per unique
        # value of name_field (e.g. one Route per envoy_cluster_name).
        qs = ModelClass.objects.order_by(name_field).distinct(name_field)

        if names := request.POST.get("resource_names"):
            if len(names) == 1 and names[0] == "*":
                return qs
            qs = qs.filter(**{f"{name_field}__in": names})

        return qs

    def get_xds_response(self, ResourceType, resources):
        """Wrap a list of resource dicts into a protobuf DiscoveryResponse."""
        response = DiscoveryResponse()
        for resource in resources:
            c = ResourceType()
            ParseDict(resource, c, descriptor_pool=symbol_database.Default().pool)

            a = Any()
            a.Pack(c)

            response.resources.append(a)

        return MessageToDict(response)


class ClusterDiscoverServiceView(XDSView):
    """CDS -- returns an Envoy Cluster definition for every Route."""

    def post(self, request, format=None):
        routes = list(self.get_qs(request, Route, "envoy_cluster_name").select_related('service_cluster'))

        # Pre-compute the maximum per-route request_timeout_seconds for each
        # ServiceCluster in a single query.  We stash the result as the
        # _max_route_timeout attribute so that
        # ServiceCluster.get_effective_health_check_timeout_seconds() can use
        # it instead of issuing a per-cluster aggregate (N+1).
        cluster_ids = {r.service_cluster_id for r in routes}
        max_timeouts = dict(ServiceCluster.objects.filter(pk__in=cluster_ids).annotate(_max=Max('routes__request_timeout_seconds')).values_list('pk', '_max'))
        for route in routes:
            route.service_cluster._max_route_timeout = max_timeouts.get(route.service_cluster_id)

        clusters = [x.get_xds_cluster_config() for x in routes]
        return Response(self.get_xds_response(Cluster, clusters))


class ListenerDiscoverServiceView(XDSView):
    """LDS -- returns an Envoy Listener for every HTTPPort."""

    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        listeners = [x.get_xds_listener_config() for x in self.get_qs(request, HTTPPort, "envoy_listener_name")]

        return Response(self.get_xds_response(Listener, listeners))


class SecretDiscoverServiceView(XDSView):
    """SDS -- returns a single Secret containing all trusted CA certificates."""

    # No authentication by design -- only reachable from Envoy on loopback.
    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        secret_resource = self._collect_db_ca_certs()
        return Response(self.get_xds_response(Secret, [secret_resource]))

    def _collect_db_ca_certs(self) -> dict:
        pem_blocks = [(cert.pem_data or "").strip() for cert in CACertificate.objects.all()]
        pem_blocks = [p for p in pem_blocks if p]
        secret = {"name": SDS_SECRET_CONFIG_NAME, "validation_context": {}}
        if pem_blocks:
            secret["validation_context"]["trusted_ca"] = {"inline_string": "\n".join(pem_blocks)}
        return secret
