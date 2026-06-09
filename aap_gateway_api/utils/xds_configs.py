from django.conf import settings

from aap_gateway_api.common.envoy import (
    DOWNSTREAM_TLS_CONTEXT,
    EXT_AUTHZ_FILTER,
    HTTP_CONNECTION_MANAGER,
    HTTP_ROUTER,
    LUA_FILTER,
    OPENTELEMETRY_CONFIG,
    STDOUT_ACCESS_LOG,
)

SDS_SECRET_CONFIG_NAME = "validation_context_sds"


def path_rewrite_filter():
    return {
        "name": "lua_path_rewrite",
        "typed_config": {
            "@type": LUA_FILTER,
            "source_codes": {"rewrite.lua": {"filename": settings.GATEWAY_PATH_REWRITE_SCRIPT_FILE}},
        },
    }


def external_auth_filter():
    return {
        "name": "envoy.filters.http.ext_authz",
        "typed_config": {
            "@type": EXT_AUTHZ_FILTER,
            "grpc_service": {
                "envoy_grpc": {"cluster_name": "gateway_control_plane"},
                "timeout": settings.GRPC_SERVER_AUTH_SERVICE_TIMEOUT,
            },
            "transport_api_version": "V3",
            "with_request_body": {
                # Subtract 8KiB max GRPC header length: https://grpc.io/docs/guides/metadata/#be-aware
                "max_request_bytes": settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH - 8192,
                "allow_partial_message": True,
                "pack_as_bytes": True,
            },
            "status_on_error": {"code": "BadGateway"},
        },
    }


def http_router_filter():
    return {"name": "envoy.filters.http.router", "typed_config": {"@type": HTTP_ROUTER}}


def network_manager_filter(http_filters=[], routes=[]):
    return {
        "name": "envoy.filters.network.http_connection_manager",
        "typed_config": {
            "@type": HTTP_CONNECTION_MANAGER,
            "stat_prefix": "ingress_http",
            "upgrade_configs": [
                {"upgrade_type": "websocket"},
            ],
            "access_log": [
                {
                    "name": "envoy.access_loggers.stdout",
                    "typed_config": {"@type": STDOUT_ACCESS_LOG},
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
            "tracing": {
                "provider": {
                    "name": "envoy.tracers.opentelemetry",
                    "typed_config": {
                        "@type": OPENTELEMETRY_CONFIG,
                        "grpc_service": {"envoy_grpc": {"cluster_name": "otel_collector"}},
                        "service_name": "gateway-envoy",
                    },
                }
            },
            "use_remote_address": True,
            "xff_num_trusted_hops": settings.XDS_XFF_NUM_TRUSTED_HOPS,
        },
    }


def transport_socket():
    return {
        "name": "envoy.transport_sockets.tls",
        "typed_config": {
            "@type": DOWNSTREAM_TLS_CONTEXT,
            "require_client_certificate": False,
            "common_tls_context": {
                "tls_certificates": [
                    {
                        "certificate_chain": {"filename": settings.GATEWAY_CERT_FILE},
                        "private_key": {"filename": settings.GATEWAY_KEY_FILE},
                    }
                ],
                "validation_context_sds_secret_config": {
                    "name": SDS_SECRET_CONFIG_NAME,
                    "sds_config": _rest_sds_config(),
                },
            },
        },
    }


def _rest_sds_config() -> dict:
    return {
        "api_config_source": {
            "api_type": "REST",
            "transport_api_version": "V3",
            "cluster_names": settings.SDS_CLUSTER_NAMES,
            "refresh_delay": settings.SDS_REFRESH_DELAY_PROTOBUF_DURATION,
        }
    }
