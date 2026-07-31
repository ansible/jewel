"""Unit tests for Route model xDS config generation and ext_auth behaviour."""

import pytest
from ansible_base.feature_flags.utils import create_initial_data as seed_feature_flags

from aap_gateway_api.common.envoy import AUTH_TYPE_NONE
from aap_gateway_api.models import AdditionalRoute, DefaultServiceType, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceType, UIPluginRoute
from aap_gateway_api.models.service_node import ServiceNode


class TestRoute:
    @pytest.mark.django_db
    def test_xds_login_logout_missing_models(self):
        route = ServiceAPIRoute()
        # First fail because of the missing service cluster
        routes = route.get_xds_login_logout_routes()
        assert len(routes) == 0

        # Now fail because of a missing gateway route
        st = ServiceType.objects.get(name=DefaultServiceType.GATEWAY.value)
        ServiceCluster.objects.create(service_type=st)
        routes = route.get_xds_login_logout_routes()
        assert len(routes) == 0

    @pytest.mark.django_db
    def test_xds_login_logout_not_type_service(self):
        route = AdditionalRoute()
        routes = route.get_xds_login_logout_routes()
        assert len(routes) == 0

    @pytest.mark.django_db
    def test_xds_login_logout_gateway_does_not_have_routes(self, service_api_route_gateway):
        routes = service_api_route_gateway.get_xds_login_logout_routes()
        assert len(routes) == 0

    @pytest.mark.parametrize(
        "service",
        [
            ('controller'),
            ('eda'),
            ('hub'),
        ],
    )
    @pytest.mark.django_db
    def test_xds_login_logout_services_have_routes(
        # We don't use service_api_route_gateway but the code needs it there.
        self,
        service,
        service_api_route_gateway,
        service_api_route_controller,
        service_api_route_eda,
        service_api_route_hub,
    ):
        routes = []
        if service == 'controller':
            routes = service_api_route_controller.get_xds_login_logout_routes()
        elif service == 'eda':
            routes = service_api_route_eda.get_xds_login_logout_routes()
        elif service == 'hub':
            routes = service_api_route_hub.get_xds_login_logout_routes()

        assert len(routes) == 2

    @pytest.mark.django_db
    def test_xds_route_config_missing_data(self, service_cluster_eda):
        route = AdditionalRoute()
        # First fail because of the missing service cluster
        routes = route.get_xds_route_config()
        assert len(routes) == 0

        route.gateway_path = '/'
        routes = route.get_xds_route_config()
        assert len(routes) == 0

        route.service_path = '/'
        routes = route.get_xds_route_config()
        assert len(routes) == 0

        route.envoy_cluster_name = 'testing'
        route.service_cluster = service_cluster_eda
        routes = route.get_xds_route_config()
        assert len(routes) == 1

    @pytest.mark.django_db
    def test_xds_route_config_paths_equal(self, service_cluster_eda):
        route = ServiceAPIRoute(gateway_path='/', service_path='/', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'envoy.filters.http.lua' not in routes[0]["typed_per_filter_config"]

    @pytest.mark.django_db
    def test_xds_route_config_paths_different(self, service_cluster_eda):
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'filter_metadata' in routes[0]["metadata"]
        assert 'envoy.filters.http.lua' in routes[0]["typed_per_filter_config"]

    @pytest.mark.django_db
    def test_xds_route_config_enable_gateway_auth(self, service_cluster_eda):
        route = ServiceAPIRoute(
            gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=True, service_cluster=service_cluster_eda
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'disabled' not in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'check_settings' in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'is_internal_route' in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]
        assert routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]["is_internal_route"] == "f"

    @pytest.mark.django_db
    def test_xds_route_config_enable_gateway_auth_internal_route(self, service_cluster_eda):
        route = ServiceAPIRoute(
            gateway_path='/',
            service_path='/path',
            envoy_cluster_name='testing',
            enable_gateway_auth=True,
            is_internal_route=True,
            service_cluster=service_cluster_eda,
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'disabled' not in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'check_settings' in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'is_internal_route' in routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]
        assert routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]["is_internal_route"] == "t"

    @pytest.mark.django_db
    def test_xds_route_config_disable_gateway_auth_for_eda(self, service_cluster_eda):
        """
        Test that EDA routes with enable_gateway_auth=False use AUTH_TYPE_NONE.
        This allows EDA webhooks to handle their own auth while still getting X-Trusted-Proxy.
        """
        route = ServiceAPIRoute(
            gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=False, service_cluster=service_cluster_eda
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'envoy.filters.http.ext_authz' in routes[0]["typed_per_filter_config"]

        # Verify the new structure: uses check_settings with auth_type=NONE instead of disabled=True
        ext_authz_config = routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'disabled' not in ext_authz_config, "EDA routes should NOT disable ext_auth completely"
        assert 'check_settings' in ext_authz_config
        assert 'context_extensions' in ext_authz_config["check_settings"]

        context_extensions = ext_authz_config["check_settings"]["context_extensions"]
        assert context_extensions["auth_type"] == AUTH_TYPE_NONE
        assert context_extensions["service_type"] == service_cluster_eda.service_type.name
        assert context_extensions["is_internal_route"] == "f"  # ServiceAPIRoute defaults to is_internal_route=False

    @pytest.mark.django_db
    def test_eda_event_stream_route_gets_trusted_proxy_config(self, service_cluster_eda):
        """
        Simulate an EDA event stream webhook route (enable_gateway_auth=False).
        Verify the xDS config enables ext_auth with AUTH_TYPE_NONE so the control
        plane adds X-Trusted-Proxy, allowing EDA to verify the request came through
        the gateway. This is the core CVE fix behavior (AAP-79215/79216).
        """
        route = ServiceAPIRoute(
            gateway_path='/api/eda/v1/external-event-stream/',
            service_path='/api/eda/v1/external-event-stream/',
            envoy_cluster_name='eda-cluster',
            enable_gateway_auth=False,
            service_cluster=service_cluster_eda,
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1

        ext_authz_config = routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'disabled' not in ext_authz_config, "EDA event stream routes must NOT disable ext_auth"
        assert ext_authz_config["check_settings"]["context_extensions"]["auth_type"] == AUTH_TYPE_NONE
        assert ext_authz_config["check_settings"]["context_extensions"]["service_type"] == "eda"

    @pytest.mark.django_db
    @pytest.mark.parametrize("service_type_fixture", ["service_cluster_hub", "service_cluster_controller"])
    def test_non_eda_services_disable_ext_auth(self, service_type_fixture, request):
        """
        Verify that non-EDA services (hub, controller) with enable_gateway_auth=False
        completely disable ext_auth, preventing gRPC calls that could be misrouted
        through corporate proxies in restricted network environments (AAP-83727).
        """
        service_cluster = request.getfixturevalue(service_type_fixture)
        route = ServiceAPIRoute(
            gateway_path='/',
            service_path='/path',
            envoy_cluster_name='testing',
            enable_gateway_auth=False,
            service_cluster=service_cluster,
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1

        ext_authz_config = routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert ext_authz_config.get('disabled') is True, f"{service_cluster.service_type.name} routes must disable ext_auth"
        assert 'check_settings' not in ext_authz_config

    @pytest.mark.django_db
    def test_service_type_is_eda_service(self, service_cluster_gateway, service_cluster_eda):
        """Verify ServiceType.is_eda_service cached_property identifies EDA vs non-EDA."""
        assert service_cluster_eda.service_type.is_eda_service is True
        assert service_cluster_gateway.service_type.is_eda_service is False

    @pytest.mark.django_db
    def test_is_eda_service_property(self, service_cluster_gateway, service_cluster_eda):
        """Verify the Route.is_eda_service property delegates correctly to ServiceType."""
        gw_route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_gateway)
        eda_route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        assert gw_route.is_eda_service is False
        assert eda_route.is_eda_service is True

    @pytest.mark.django_db
    def test_xds_route_config_disable_gateway_auth_for_non_eda(self, service_cluster_gateway):
        """
        Test that non-EDA routes with enable_gateway_auth=False completely disable ext_auth.
        Only EDA needs AUTH_TYPE_NONE for X-Trusted-Proxy; all other services restore
        pre-CVE-fix behavior to avoid 403s and gRPC misrouting in proxy environments.
        """
        route = ServiceAPIRoute(
            gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=False, service_cluster=service_cluster_gateway
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'envoy.filters.http.ext_authz' in routes[0]["typed_per_filter_config"]

        ext_authz_config = routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]
        assert 'disabled' in ext_authz_config, "Non-EDA routes MUST disable ext_auth completely"
        assert ext_authz_config['disabled'] is True
        assert 'check_settings' not in ext_authz_config, "Non-EDA routes should not have check_settings"

    @pytest.mark.parametrize(
        "service,expected_route_len",
        [
            ('controller', 3),
            ('eda', 3),
            ('hub', 3),
            ('gateway', 1),
        ],
    )
    @pytest.mark.django_db
    def test_xds_route_config(
        self, service, expected_route_len, service_api_route_gateway, service_api_route_controller, service_api_route_eda, service_api_route_hub
    ):
        if service == 'controller':
            routes = service_api_route_controller.get_xds_route_config()
        elif service == 'eda':
            routes = service_api_route_eda.get_xds_route_config()
        elif service == 'hub':
            routes = service_api_route_hub.get_xds_route_config()
        elif service == 'gateway':
            routes = service_api_route_gateway.get_xds_route_config()

        assert len(routes) == expected_route_len

    @pytest.mark.django_db
    def test_xds_route_config_service_type_auth_type(self, service_cluster_eda):
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]["service_type"] == "eda"
        assert routes[0]["typed_per_filter_config"]["envoy.filters.http.ext_authz"]["check_settings"]["context_extensions"]["auth_type"] == "JWT"

    @pytest.mark.django_db
    def test_xds_route_config_ui_plugin_path(self, service_cluster_eda):
        route = UIPluginRoute(gateway_path='/', ui_plugin_path='/plugin/', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert routes[0]["route"]["prefix_rewrite"] == "/plugin/"
        assert routes[0]["metadata"]["filter_metadata"]["envoy.filters.http.lua"]["prefix"] == "/"
        assert routes[0]["metadata"]["filter_metadata"]["envoy.filters.http.lua"]["prefix_rewrite"] == "/plugin/"

    @pytest.mark.django_db
    def test_xds_route_config_host_rewrite_literal(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "example.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert routes[0]["route"]["host_rewrite_literal"] == "example.com"

    @pytest.mark.django_db
    def test_xds_cluster_config_host_sni(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "example.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.is_service_https = True
        cluster = route.get_xds_cluster_config()
        assert cluster["transport_socket"]["typed_config"]["sni"] == "example.com"

        service_cluster_eda.upstream_hostname = None
        cluster = route.get_xds_cluster_config()
        assert "sni" not in cluster["transport_socket"]["typed_config"]

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "address,hostname",
        [
            ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", "[2001:0db8:85a3:0000:0000:8a2e:0370:7334]"),
            ("0.0.0.0", "0.0.0.0"),
        ],
    )
    def test_xds_cluster_config_health_checks_enabled(self, address, hostname, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "example.com"
        service_cluster_eda.health_checks_enabled = True
        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="my-eda-service-node",
                    service_cluster=service_cluster_eda,
                    address=address,
                    tags="eda",
                )
            ]
        )
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.node_tags = "eda"

        # Use DAB feature flags API as documented
        seed_feature_flags()

        cluster = route.get_xds_cluster_config()
        endpoint = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
        assert endpoint["address"]["socket_address"]["address"] == address
        assert endpoint["health_check_config"]["hostname"] == hostname

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "node_address,expected_health_check_hostname,upstream_hostname",
        [
            # Expanded IPv6 address
            ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", "[2001:0db8:85a3:0000:0000:8a2e:0370:7334]", "example.com"),
            # Compressed IPv6 address
            ("2001:db8:85a3::8a2e:370:7334", "[2001:db8:85a3::8a2e:370:7334]", "hub.com"),
            # IPv6 with leading zeros compressed
            ("2001:db8::1", "[2001:db8::1]", "controller.com"),
            # IPv6 loopback
            ("::1", "[::1]", "gateway.com"),
            # IPv6 already bracketed (should still work correctly)
            ("[2001:db8::1]", "[2001:db8::1]", "example.com"),
            # IPv4 address (should not be bracketed)
            ("192.168.1.1", "192.168.1.1", "hub.com"),
            ("10.0.0.1", "10.0.0.1", "controller.com"),
            ("0.0.0.0", "0.0.0.0", "gateway.com"),
            # Test hostname handling - health check uses node address, not upstream_hostname
            ("192.168.1.1", "192.168.1.1", "example.com"),
            ("192.168.1.1", "192.168.1.1", "service.example.com"),
            ("192.168.1.1", "192.168.1.1", "subdomain.example.com"),
            ("192.168.1.1", "192.168.1.1", "localhost"),
        ],
    )
    def test_xds_cluster_config_address_and_hostname_handling(self, node_address, expected_health_check_hostname, upstream_hostname, service_cluster_eda):
        """Test that addresses in health checks are properly formatted and hostnames are handled correctly."""
        service_cluster_eda.upstream_hostname = upstream_hostname
        service_cluster_eda.health_checks_enabled = True

        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="my-eda-service-node",
                    service_cluster=service_cluster_eda,
                    address=node_address,
                    tags="eda",
                )
            ]
        )
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.node_tags = "eda"

        seed_feature_flags()

        cluster = route.get_xds_cluster_config()
        endpoint = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
        # Address should be stored without brackets
        assert endpoint["address"]["socket_address"]["address"] == node_address
        # Health check hostname should use node address (properly formatted), not upstream_hostname
        assert endpoint["health_check_config"]["hostname"] == expected_health_check_hostname

        # Verify upstream_hostname is used for host_rewrite_literal in route config
        routes = route.get_xds_route_config()
        assert routes[0]["route"]["host_rewrite_literal"] == upstream_hostname

    @pytest.mark.django_db
    def test_xds_cluster_config_health_checks_disabled(self, service_cluster_eda):
        """Test proper behavior when health checks are disabled."""
        service_cluster_eda.upstream_hostname = "example.com"
        service_cluster_eda.health_checks_enabled = False
        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv6",
                    service_cluster=service_cluster_eda,
                    address="2001:db8::1",
                    tags="eda",
                ),
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv4",
                    service_cluster=service_cluster_eda,
                    address="192.168.1.1",
                    tags="eda",
                ),
            ]
        )
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.node_tags = "eda"

        seed_feature_flags()

        cluster = route.get_xds_cluster_config()
        endpoints = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"]

        # Verify all endpoints are present
        assert len(endpoints) == 2

        # Verify health_check_config is not present when health checks are disabled
        for endpoint in endpoints:
            assert "health_check_config" not in endpoint["endpoint"]
            # Address should still be present
            assert "address" in endpoint["endpoint"]

        # Verify health_checks section is not in cluster config
        assert "health_checks" not in cluster

    @pytest.mark.django_db
    def test_xds_cluster_config_mixed_ipv4_ipv6(self, service_cluster_eda):
        """Test mixed IPv4/IPv6 mode (v4 address for some service nodes, v6 for others)."""
        service_cluster_eda.upstream_hostname = "example.com"
        service_cluster_eda.health_checks_enabled = True
        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv6-1",
                    service_cluster=service_cluster_eda,
                    address="2001:db8::1",
                    tags="eda",
                ),
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv6-2",
                    service_cluster=service_cluster_eda,
                    address="2001:db8::2",
                    tags="eda",
                ),
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv4-1",
                    service_cluster=service_cluster_eda,
                    address="192.168.1.1",
                    tags="eda",
                ),
                ServiceNode.objects.create(
                    name="my-eda-service-node-ipv4-2",
                    service_cluster=service_cluster_eda,
                    address="10.0.0.1",
                    tags="eda",
                ),
            ]
        )
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.node_tags = "eda"

        seed_feature_flags()

        cluster = route.get_xds_cluster_config()
        endpoints = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"]

        # Verify all endpoints are present
        assert len(endpoints) == 4

        # Verify each endpoint has correct address and health check hostname
        for endpoint in endpoints:
            address = endpoint["endpoint"]["address"]["socket_address"]["address"]
            hostname = endpoint["endpoint"]["health_check_config"]["hostname"]
            if ":" in address:  # IPv6
                assert hostname == f"[{address}]"
            else:  # IPv4
                assert hostname == address

    @pytest.mark.django_db
    def test_xds_cluster_config_dns_params(self, service_cluster_eda):
        service_cluster_eda.dns_discovery_type = ServiceCluster.DNSServiceDiscovery.LOGICAL_DNS
        service_cluster_eda.dns_lookup_family = ServiceCluster.DNSLookupFamily.V4_ONLY
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        cluster = route.get_xds_cluster_config()
        assert cluster["dns_lookup_family"] == ServiceCluster.DNSLookupFamily.V4_ONLY
        assert cluster["type"] == ServiceCluster.DNSServiceDiscovery.LOGICAL_DNS

    @pytest.mark.django_db
    def test_xds_route_config_always_emits_both_timeouts(self, service_cluster_eda, preference_manager):
        """All routes emit both timeout and idle_timeout regardless of service type."""
        with preference_manager.set_multiple(
            {
                ('proxy', 'request_timeout'): 30,
                ('proxy', 'idle_timeout'): 15,
            }
        ):
            route = ServiceAPIRoute(
                gateway_path='/api/eda/',
                service_path='/api/',
                envoy_cluster_name='eda-cluster',
                service_cluster=service_cluster_eda,
            )

            routes = route.get_xds_route_config()
            assert len(routes) == 1
            assert routes[0]["route"]["timeout"] == "30s"
            assert routes[0]["route"]["idle_timeout"] == "15s"

    @pytest.mark.django_db
    def test_xds_route_config_enable_mtls(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "example.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda, enable_mtls=True)
        routes = route.get_xds_route_config()
        assert routes[0]['match']['tls_context']['presented']
        assert routes[0]['match']['tls_context']['validated']
        assert routes[0]['request_headers_to_add'][0]['header']['key'] == 'Subject'
        assert routes[0]['request_headers_to_add'][0]['header']['value'] == '%DOWNSTREAM_PEER_SUBJECT%'
        assert routes[0]['request_headers_to_add'][0]['append'] is False

    @pytest.mark.django_db
    def test_xds_route_config_disable_mtls(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "example.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda, enable_mtls=False)
        routes = route.get_xds_route_config()
        assert 'tls_context' not in routes[0]['match'].keys()

    @pytest.mark.django_db
    def test_xds_route_config_subject_header_removed_by_default(self, service_cluster_eda):
        """Test that Subject header is removed from all requests by default to prevent spoofing."""
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert 'request_headers_to_remove' in routes[0]
        assert routes[0]['request_headers_to_remove'] == ['Subject']

    @pytest.mark.django_db
    def test_xds_route_config_mtls_subject_header_append_false(self, service_cluster_eda):
        """Test that when mTLS is enabled, the Subject header is set with append=False to prevent spoofing."""
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda, enable_mtls=True)
        routes = route.get_xds_route_config()

        # Verify Subject header is removed by default
        assert 'request_headers_to_remove' in routes[0]
        assert routes[0]['request_headers_to_remove'] == ['Subject']

        # Verify Subject header is added with append=False when mTLS is enabled
        assert 'request_headers_to_add' in routes[0]
        assert len(routes[0]['request_headers_to_add']) == 1
        subject_header = routes[0]['request_headers_to_add'][0]
        assert subject_header['header']['key'] == 'Subject'
        assert subject_header['header']['value'] == '%DOWNSTREAM_PEER_SUBJECT%'
        assert subject_header['append'] is False

    @pytest.mark.django_db
    def test_xds_route_config_mtls_disabled_no_subject_added(self, service_cluster_eda):
        """Test that when mTLS is disabled, the Subject header is removed but not re-added."""
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda, enable_mtls=False)
        routes = route.get_xds_route_config()

        # Verify Subject header is removed
        assert 'request_headers_to_remove' in routes[0]
        assert routes[0]['request_headers_to_remove'] == ['Subject']

        # Verify Subject header is NOT added when mTLS is disabled
        assert 'request_headers_to_add' not in routes[0]

    @pytest.mark.django_db
    def test_xds_route_config_additional_route_subject_removed(self, service_cluster_eda):
        """Test that AdditionalRoute also removes Subject header by default."""
        route = AdditionalRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert 'request_headers_to_remove' in routes[0]
        assert routes[0]['request_headers_to_remove'] == ['Subject']


class TestRouteRequestTimeout:
    """Tests for per-route request_timeout_seconds and idle_timeout_seconds."""

    @pytest.fixture
    def http_port(self):
        port = HTTPPort.objects.create(name="test-timeout-port", number=9999)
        yield port
        port.delete()

    @pytest.mark.parametrize(
        "route_timeout,preference_timeout,expected_timeout",
        [
            (600, 30, "600s"),
            (None, 30, "30s"),
            (10, 30, "30s"),
            (30, 30, "30s"),
        ],
        ids=[
            "route_above_preference_uses_route",
            "route_null_uses_preference",
            "route_below_preference_uses_preference",
            "route_equal_to_preference_uses_preference",
        ],
    )
    @pytest.mark.django_db
    def test_xds_route_config_request_timeout(self, route_timeout, preference_timeout, expected_timeout, service_cluster_eda, preference_manager):
        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            route = ServiceAPIRoute(
                gateway_path='/',
                service_path='/path',
                envoy_cluster_name='testing',
                service_cluster=service_cluster_eda,
                request_timeout_seconds=route_timeout,
            )
            routes = route.get_xds_route_config()
            assert routes[0]["route"]["timeout"] == expected_timeout

    @pytest.mark.parametrize(
        "route_idle,preference_idle,expected_idle",
        [
            (60, 15, "60s"),
            (None, 15, "15s"),
            (5, 15, "15s"),
            (15, 15, "15s"),
        ],
        ids=[
            "route_above_preference_uses_route",
            "route_null_uses_preference",
            "route_below_preference_uses_preference",
            "route_equal_to_preference_uses_preference",
        ],
    )
    @pytest.mark.django_db
    def test_xds_route_config_idle_timeout(self, route_idle, preference_idle, expected_idle, service_cluster_eda, preference_manager):
        with preference_manager.set("proxy", "idle_timeout", preference_idle):
            route = ServiceAPIRoute(
                gateway_path='/',
                service_path='/path',
                envoy_cluster_name='testing',
                service_cluster=service_cluster_eda,
                idle_timeout_seconds=route_idle,
            )
            routes = route.get_xds_route_config()
            assert routes[0]["route"]["idle_timeout"] == expected_idle

    @pytest.mark.parametrize(
        "route_timeout,preference_timeout,expected",
        [
            (600, 30, 600),
            (None, 30, 30),
            (10, 30, 30),
        ],
        ids=[
            "route_above_preference",
            "route_null",
            "route_below_preference",
        ],
    )
    @pytest.mark.django_db
    def test_get_effective_timeout_seconds(self, route_timeout, preference_timeout, expected, service_cluster_eda, preference_manager):
        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            route = ServiceAPIRoute(
                gateway_path='/',
                service_path='/path',
                envoy_cluster_name='testing',
                service_cluster=service_cluster_eda,
                request_timeout_seconds=route_timeout,
            )
            assert route.get_effective_timeout_seconds() == expected

    @pytest.mark.parametrize(
        "route_idle,preference_idle,expected",
        [
            (60, 15, 60),
            (None, 15, 15),
            (5, 15, 15),
        ],
        ids=[
            "route_above_preference",
            "route_null",
            "route_below_preference",
        ],
    )
    @pytest.mark.django_db
    def test_get_effective_idle_timeout_seconds(self, route_idle, preference_idle, expected, service_cluster_eda, preference_manager):
        with preference_manager.set("proxy", "idle_timeout", preference_idle):
            route = ServiceAPIRoute(
                gateway_path='/',
                service_path='/path',
                envoy_cluster_name='testing',
                service_cluster=service_cluster_eda,
                idle_timeout_seconds=route_idle,
            )
            assert route.get_effective_idle_timeout_seconds() == expected

    @pytest.mark.parametrize(
        "health_check_timeout,route_timeout,preference_timeout,expected",
        [
            (5, 600, 30, 600),
            (5, None, 30, 30),
            (700, 600, 30, 700),
            (5, None, 60, 60),
        ],
        ids=[
            "route_timeout_is_highest",
            "no_route_timeout_uses_preference_as_floor",
            "cluster_timeout_is_highest",
            "preference_is_highest_when_no_route_timeout",
        ],
    )
    @pytest.mark.django_db
    def test_effective_health_check_timeout(
        self, health_check_timeout, route_timeout, preference_timeout, expected, service_cluster_eda, http_port, preference_manager
    ):
        service_cluster_eda.health_check_timeout_seconds = health_check_timeout
        service_cluster_eda.save()

        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            AdditionalRoute.objects.create(
                name="test-timeout-route",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path",
                gateway_path="/test-path/",
                request_timeout_seconds=route_timeout,
            )
            assert service_cluster_eda.get_effective_health_check_timeout_seconds() == expected

    @pytest.mark.django_db
    def test_effective_health_check_timeout_multiple_routes(self, service_cluster_eda, http_port, preference_manager):
        service_cluster_eda.health_check_timeout_seconds = 5
        service_cluster_eda.save()

        with preference_manager.set("proxy", "request_timeout", 30):
            AdditionalRoute.objects.create(
                name="route-low-timeout",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path1",
                gateway_path="/test-path-1/",
                request_timeout_seconds=60,
            )
            AdditionalRoute.objects.create(
                name="route-high-timeout",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path2",
                gateway_path="/test-path-2/",
                request_timeout_seconds=600,
            )
            AdditionalRoute.objects.create(
                name="route-null-timeout",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path3",
                gateway_path="/test-path-3/",
                request_timeout_seconds=None,
            )
            assert service_cluster_eda.get_effective_health_check_timeout_seconds() == 600

    @pytest.mark.django_db
    def test_xds_cluster_config_uses_effective_health_check_timeout(self, service_cluster_eda, http_port, preference_manager):
        service_cluster_eda.health_checks_enabled = True
        service_cluster_eda.health_check_timeout_seconds = 5
        service_cluster_eda.save()
        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="node-for-timeout-test",
                    service_cluster=service_cluster_eda,
                    address="10.0.0.1",
                    tags="eda",
                )
            ]
        )

        seed_feature_flags()

        with preference_manager.set("proxy", "request_timeout", 30):
            route = AdditionalRoute.objects.create(
                name="timeout-xds-test-route",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path",
                gateway_path="/xds-test/",
                request_timeout_seconds=600,
            )
            route.node_tags = "eda"
            cluster_cfg = route.get_xds_cluster_config()
            assert cluster_cfg["health_checks"][0]["timeout"] == "600s"

    @pytest.mark.parametrize(
        "health_check_interval,health_check_timeout,route_timeout,preference_timeout,expected_interval",
        [
            (0, 5, None, 30, 30),
            (10, 5, None, 30, 30),
            (30, 5, None, 30, 30),
            (60, 5, None, 30, 60),
            (10, 5, 600, 30, 600),
            (700, 5, 600, 30, 700),
        ],
        ids=[
            "zero_interval_uses_effective_timeout",
            "interval_below_effective_timeout_uses_effective_timeout",
            "interval_equals_effective_timeout",
            "interval_above_effective_timeout_preserved",
            "interval_below_route_timeout_uses_route_timeout",
            "interval_above_route_timeout_preserved",
        ],
    )
    @pytest.mark.django_db
    def test_effective_health_check_interval(
        self,
        health_check_interval,
        health_check_timeout,
        route_timeout,
        preference_timeout,
        expected_interval,
        service_cluster_eda,
        http_port,
        preference_manager,
    ):
        service_cluster_eda.health_check_timeout_seconds = health_check_timeout
        service_cluster_eda.health_check_interval_seconds = health_check_interval
        service_cluster_eda.save()

        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            AdditionalRoute.objects.create(
                name="test-interval-route",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path",
                gateway_path="/test-interval/",
                request_timeout_seconds=route_timeout,
            )
            assert service_cluster_eda.get_effective_health_check_interval_seconds() == expected_interval

    @pytest.mark.django_db
    def test_xds_cluster_config_uses_effective_health_check_interval(self, service_cluster_eda, http_port, preference_manager):
        service_cluster_eda.health_checks_enabled = True
        service_cluster_eda.health_check_timeout_seconds = 5
        service_cluster_eda.health_check_interval_seconds = 10
        service_cluster_eda.save()
        service_cluster_eda.nodes.set(
            [
                ServiceNode.objects.create(
                    name="node-for-interval-test",
                    service_cluster=service_cluster_eda,
                    address="10.0.0.1",
                    tags="eda",
                )
            ]
        )

        seed_feature_flags()

        with preference_manager.set("proxy", "request_timeout", 30):
            route = AdditionalRoute.objects.create(
                name="interval-xds-test-route",
                http_port=http_port,
                is_service_https=False,
                service_cluster=service_cluster_eda,
                service_port=8080,
                service_path="/path",
                gateway_path="/xds-interval-test/",
                request_timeout_seconds=600,
            )
            route.node_tags = "eda"
            cluster_cfg = route.get_xds_cluster_config()
            assert cluster_cfg["health_checks"][0]["timeout"] == "600s"
            assert cluster_cfg["health_checks"][0]["interval"] == "600s"
