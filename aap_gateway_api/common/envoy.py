from envoy.config.trace.v3 import opentelemetry_pb2
from envoy.extensions.access_loggers.stream.v3 import stream_pb2
from envoy.extensions.filters.http.ext_authz.v3 import ext_authz_pb2
from envoy.extensions.filters.http.lua.v3 import lua_pb2
from envoy.extensions.filters.http.router.v3 import router_pb2
from envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2
from envoy.extensions.transport_sockets.tls.v3 import tls_pb2

_TYPE_URL_PREFIX = "type.googleapis.com"


def _type_url(descriptor) -> str:
    return f"{_TYPE_URL_PREFIX}/{descriptor.full_name}"


# Filter name used in Envoy filter chain config — not a type URL.
EXT_AUTH_FILTER = "envoy.filters.http.ext_authz"
AUTH_TYPE_NONE = "NONE"

# Type URLs derived from protobuf message descriptors.
EXT_AUTH_PER_ROUTE = _type_url(ext_authz_pb2.ExtAuthzPerRoute.DESCRIPTOR)
UPSTREAM_TLS_CONTEXT = _type_url(tls_pb2.UpstreamTlsContext.DESCRIPTOR)
DOWNSTREAM_TLS_CONTEXT = _type_url(tls_pb2.DownstreamTlsContext.DESCRIPTOR)
LUA_FILTER = _type_url(lua_pb2.Lua.DESCRIPTOR)
LUA_PER_ROUTE = _type_url(lua_pb2.LuaPerRoute.DESCRIPTOR)
EXT_AUTHZ_FILTER = _type_url(ext_authz_pb2.ExtAuthz.DESCRIPTOR)
HTTP_ROUTER = _type_url(router_pb2.Router.DESCRIPTOR)
HTTP_CONNECTION_MANAGER = _type_url(http_connection_manager_pb2.HttpConnectionManager.DESCRIPTOR)
STDOUT_ACCESS_LOG = _type_url(stream_pb2.StdoutAccessLog.DESCRIPTOR)
OPENTELEMETRY_CONFIG = _type_url(opentelemetry_pb2.OpenTelemetryConfig.DESCRIPTOR)
