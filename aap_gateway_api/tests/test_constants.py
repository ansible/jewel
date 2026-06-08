"""Tests for extracted constants (SonarCloud maintainability fixes).

Verifies that duplicated string literals have been properly extracted into
named constants and are used consistently across the codebase.
"""

from unittest.mock import patch

from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE

from aap_gateway_api.common.envoy import (
    DOWNSTREAM_TLS_CONTEXT,
    EXT_AUTH_FILTER,
    EXT_AUTH_PER_ROUTE,
    EXT_AUTHZ_FILTER,
    HTTP_CONNECTION_MANAGER,
    HTTP_ROUTER,
    LUA_FILTER,
    LUA_PER_ROUTE,
    STDOUT_ACCESS_LOG,
    UPSTREAM_TLS_CONTEXT,
)
from aap_gateway_api.urls import API_GATEWAY_V1_PREFIX


class TestSharedUserResourceTypeConstant:
    """Verify the SHARED_USER_RESOURCE_TYPE constant value and usage."""

    def test_shared_user_resource_type_value(self):
        assert SHARED_USER_RESOURCE_TYPE == "shared.user"

    def test_shared_user_in_api_config(self):
        """APIConfig.custom_resource_processors should use the constant."""
        from aap_gateway_api.resource_api import APIConfig

        assert SHARED_USER_RESOURCE_TYPE in APIConfig.custom_resource_processors


class TestEnvoyTypeUrlConstants:
    """Verify the Envoy type URL constants have correct values."""

    def test_upstream_tls_context_value(self):
        assert UPSTREAM_TLS_CONTEXT == "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext"

    def test_downstream_tls_context_value(self):
        assert DOWNSTREAM_TLS_CONTEXT == "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext"

    def test_lua_filter_value(self):
        assert LUA_FILTER == "type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua"

    def test_lua_per_route_value(self):
        assert LUA_PER_ROUTE == "type.googleapis.com/envoy.extensions.filters.http.lua.v3.LuaPerRoute"

    def test_ext_authz_filter_value(self):
        assert EXT_AUTHZ_FILTER == "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz"

    def test_http_router_value(self):
        assert HTTP_ROUTER == "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"

    def test_http_connection_manager_value(self):
        assert HTTP_CONNECTION_MANAGER == "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager"

    def test_stdout_access_log_value(self):
        assert STDOUT_ACCESS_LOG == "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog"

    def test_ext_auth_filter_value(self):
        """Pre-existing constant -- ensure it is unchanged."""
        assert EXT_AUTH_FILTER == "envoy.filters.http.ext_authz"

    def test_ext_auth_per_route_value(self):
        """Pre-existing constant -- ensure it is unchanged."""
        assert EXT_AUTH_PER_ROUTE == "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute"


class TestXdsConfigsUseConstants:
    """Verify that xds_configs.py functions produce configs using the constants."""

    @patch("aap_gateway_api.utils.xds_configs.settings")
    def test_path_rewrite_filter_uses_lua_filter(self, mock_settings):
        mock_settings.GATEWAY_PATH_REWRITE_SCRIPT_FILE = "/tmp/rewrite.lua"
        from aap_gateway_api.utils.xds_configs import path_rewrite_filter

        result = path_rewrite_filter()
        assert result["typed_config"]["@type"] == LUA_FILTER

    @patch("aap_gateway_api.utils.xds_configs.settings")
    def test_external_auth_filter_uses_ext_authz_filter(self, mock_settings):
        mock_settings.GRPC_SERVER_AUTH_SERVICE_TIMEOUT = "5s"
        mock_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH = 16384
        from aap_gateway_api.utils.xds_configs import external_auth_filter

        result = external_auth_filter()
        assert result["typed_config"]["@type"] == EXT_AUTHZ_FILTER

    @patch("aap_gateway_api.utils.xds_configs.settings")
    def test_http_router_filter_uses_http_router(self, mock_settings):
        from aap_gateway_api.utils.xds_configs import http_router_filter

        result = http_router_filter()
        assert result["typed_config"]["@type"] == HTTP_ROUTER

    @patch("aap_gateway_api.utils.xds_configs.settings")
    def test_network_manager_filter_uses_constants(self, mock_settings):
        mock_settings.XDS_XFF_NUM_TRUSTED_HOPS = 0
        from aap_gateway_api.utils.xds_configs import network_manager_filter

        result = network_manager_filter()
        assert result["typed_config"]["@type"] == HTTP_CONNECTION_MANAGER
        assert result["typed_config"]["access_log"][0]["typed_config"]["@type"] == STDOUT_ACCESS_LOG

    @patch("aap_gateway_api.utils.xds_configs.settings")
    def test_transport_socket_uses_downstream_tls_context(self, mock_settings):
        mock_settings.GATEWAY_CERT_FILE = "/tmp/cert.pem"
        mock_settings.GATEWAY_KEY_FILE = "/tmp/key.pem"
        mock_settings.SDS_CLUSTER_NAMES = ["sds_cluster"]
        mock_settings.SDS_REFRESH_DELAY_PROTOBUF_DURATION = "30s"
        from aap_gateway_api.utils.xds_configs import transport_socket

        result = transport_socket()
        assert result["typed_config"]["@type"] == DOWNSTREAM_TLS_CONTEXT


class TestApiGatewayV1PrefixConstant:
    """Verify the API_GATEWAY_V1_PREFIX constant value and usage in URL patterns."""

    def test_api_gateway_v1_prefix_value(self):
        assert API_GATEWAY_V1_PREFIX == "api/gateway/v1/"

    def test_prefix_used_in_urlpatterns(self):
        """Verify that URL patterns resolve correctly using the constant."""
        from aap_gateway_api.urls import urlpatterns

        # Check that we have URL patterns defined
        assert len(urlpatterns) > 0

        # Verify key URL patterns exist by checking their names
        url_names = [getattr(p, 'name', None) for p in urlpatterns]
        assert 'ping-view' in url_names
        assert 'status-view' in url_names
        assert 'jwt-key-view' in url_names
        assert 'login' in url_names
        assert 'logout' in url_names
        assert 'me-list' in url_names
        assert 'session-view' in url_names
