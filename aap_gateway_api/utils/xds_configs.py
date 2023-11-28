from django.conf import settings


def path_rewrite_filter():
    return {
        "name": "lua_path_rewrite",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua",
            "source_codes": {"rewrite.lua": {"filename": "/etc/envoy/envoy-path-rewrite.lua"}},
        },
    }


def external_auth_filter():
    return {
        "name": "envoy.filters.http.ext_authz",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz",
            "grpc_service": {"envoy_grpc": {"cluster_name": "gateway_control_plane"}, "timeout": "0.5s"},
            "transport_api_version": "V3",
        },
    }


def http_router_filter():
    return {"name": "envoy.filters.http.router", "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"}}


def network_manager_filter(http_filters=[], routes=[]):
    return {
        "name": "envoy.filters.network.http_connection_manager",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
            "stat_prefix": "ingress_http",
            "access_log": [
                {
                    "name": "envoy.access_loggers.stdout",
                    "typed_config": {"@type": "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog"},
                },
            ],
            "http_filters": http_filters,
            "route_config": {
                "name": "local_route",
                "virtual_hosts": [
                    {
                        "name": "local_route",
                        "domains": [
                            "*",
                        ],
                        "routes": routes,
                    }
                ],
            },
        },
    }


def transport_socket():
    return {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext",
            "common_tls_context": {
                "tls_certificates": [{"certificate_chain": {"filename": settings.GATEWAY_CERT_FILE}, "private_key": {"filename": settings.GATEWAY_KEY_FILE}}]
            },
        },
    }
