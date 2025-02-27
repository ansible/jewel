from django.db import connection
from django.db.models import F, OuterRef, Subquery
from envoy.config.cluster.v3.cluster_pb2 import Cluster
from envoy.config.listener.v3.listener_pb2 import Listener
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryResponse
from google.protobuf import symbol_database
from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import MessageToDict, ParseDict
from rest_framework.response import Response
from rest_framework.views import APIView

from aap_gateway_api.models import HTTPPort, Route

# these have to be imported even though they aren't used so that they get registered
# with symbol_database.Default().pool
# isort: off
from envoy.extensions.transport_sockets.tls.v3 import tls_pb2  # noqa: 401
from envoy.extensions.filters.http.router.v3 import router_pb2  # noqa: 401
from envoy.extensions.filters.http.lua.v3 import lua_pb2  # noqa: 401
from envoy.extensions.access_loggers.stream.v3 import stream_pb2  # noqa: 401
from envoy.extensions.filters.http.ext_authz.v3 import ext_authz_pb2  # noqa: 401
from envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2  # noqa: 401
from drf_spectacular.utils import extend_schema

# isort: on


@extend_schema(exclude=True)
class XDSView(APIView):
    authentication_classes = []
    permission_classes = []

    def get_qs(self, request, ModelClass, name_field):
        if connection.vendor == "postgresql":
            qs = ModelClass.objects.order_by(name_field).distinct(name_field)
        else:
            # 'DISTINCT ON' is a PostgreSQL extension, for everything else we have to do it differently.
            subquery = ModelClass.objects.filter(**{name_field: OuterRef(name_field)}).order_by("id").values("id")[:1]
            qs = ModelClass.objects.annotate(first_id=Subquery(subquery)).filter(id=F("first_id")).order_by(name_field)

        if names := request.POST.get("resource_names"):
            if len(names) == 1 and names[0] == "*":
                return qs
            qs = qs.filter(**{f"{name_field}__in": names})

        return qs

    def get_xds_response(self, ResourceType, resources):
        response = DiscoveryResponse()
        for resource in resources:
            # load the Cluster object from our config dict
            c = ResourceType()
            ParseDict(resource, c, descriptor_pool=symbol_database.Default().pool)

            # convert the Cluster message to Any
            a = Any()
            a.Pack(c)

            response.resources.append(a)

        return MessageToDict(response)


class ClusterDiscoverServiceView(XDSView):
    def post(self, request, format=None):
        clusters = [x.get_xds_cluster_config() for x in self.get_qs(request, Route, "envoy_cluster_name")]

        return Response(self.get_xds_response(Cluster, clusters))


class ListenerDiscoverServiceView(XDSView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, format=None):
        listeners = [x.get_xds_listener_config() for x in self.get_qs(request, HTTPPort, "envoy_listener_name")]

        return Response(self.get_xds_response(Listener, listeners))
