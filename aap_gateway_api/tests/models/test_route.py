import pytest
from ansible_base.feature_flags.utils import create_initial_data as seed_feature_flags

from aap_gateway_api.models import AdditionalRoute, DefaultServiceType, ServiceAPIRoute, ServiceCluster, ServiceType, UIPluginRoute
from aap_gateway_api.models.service_node import ServiceNode


class TestRoute:
    @pytest.mark.django_db()
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
    def test_xds_route_config_disable_gateway_auth(self, service_cluster_eda):
        route = ServiceAPIRoute(
            gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=False, service_cluster=service_cluster_eda
        )
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'envoy.filters.http.ext_authz' in routes[0]["typed_per_filter_config"]

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
        service_cluster_eda.upstream_hostname = "eda.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        routes = route.get_xds_route_config()
        assert routes[0]["route"]["host_rewrite_literal"] == "eda.com"

    @pytest.mark.django_db
    def test_xds_cluster_config_host_sni(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "eda.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda)
        route.is_service_https = True
        cluster = route.get_xds_cluster_config()
        assert cluster["transport_socket"]["typed_config"]["sni"] == "eda.com"

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
        service_cluster_eda.upstream_hostname = "eda.com"
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
            ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", "[2001:0db8:85a3:0000:0000:8a2e:0370:7334]", "eda.com"),
            # Compressed IPv6 address
            ("2001:db8:85a3::8a2e:370:7334", "[2001:db8:85a3::8a2e:370:7334]", "hub.com"),
            # IPv6 with leading zeros compressed
            ("2001:db8::1", "[2001:db8::1]", "controller.com"),
            # IPv6 loopback
            ("::1", "[::1]", "gateway.com"),
            # IPv6 already bracketed (should still work correctly)
            ("[2001:db8::1]", "[2001:db8::1]", "eda.com"),
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
        service_cluster_eda.upstream_hostname = "eda.com"
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
        service_cluster_eda.upstream_hostname = "eda.com"
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

    @pytest.mark.parametrize(
        "service_type_name,expected_timeout,expected_idle_timeout",
        [
            ("lightspeed", "7200s", "120s"),  # Streaming service gets both timeouts
            ("eda", "30s", None),  # Non-streaming service gets only request timeout
        ],
    )
    @pytest.mark.django_db
    def test_xds_route_config_timeout_by_service_type(self, service_type_name, expected_timeout, expected_idle_timeout, preference_manager):
        """Test that route timeout configuration varies by service type"""
        # Set up all timeout preferences
        with preference_manager.set_multiple(
            {
                ('proxy', 'request_timeout'): 30,
                ('proxy', 'stream_idle_timeout'): 120,
                ('proxy', 'max_stream_duration'): 7200,
            }
        ):
            # Create service type and cluster
            service_type, _ = ServiceType.objects.get_or_create(name=service_type_name)
            service_cluster, _ = ServiceCluster.objects.get_or_create(name=service_type_name, service_type=service_type)

            # Create route
            route = ServiceAPIRoute(
                gateway_path=f'/api/{service_type_name}/',
                service_path='/api/',
                envoy_cluster_name=f'{service_type_name}-cluster',
                service_cluster=service_cluster,
            )

            routes = route.get_xds_route_config()
            assert len(routes) == 1

            # Check timeout configuration
            assert routes[0]["route"]["timeout"] == expected_timeout

            if expected_idle_timeout:
                assert routes[0]["route"]["idle_timeout"] == expected_idle_timeout
            else:
                assert "idle_timeout" not in routes[0]["route"]

    @pytest.mark.django_db
    def test_xds_route_config_enable_mtls(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "eda.com"
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', service_cluster=service_cluster_eda, enable_mtls=True)
        routes = route.get_xds_route_config()
        assert routes[0]['match']['tls_context']['presented']
        assert routes[0]['match']['tls_context']['validated']
        assert routes[0]['request_headers_to_add'][0]['header']['key'] == 'Subject'
        assert routes[0]['request_headers_to_add'][0]['header']['value'] == '%DOWNSTREAM_PEER_SUBJECT%'
        assert routes[0]['request_headers_to_add'][0]['append'] is False

    @pytest.mark.django_db
    def test_xds_route_config_disable_mtls(self, service_cluster_eda):
        service_cluster_eda.upstream_hostname = "eda.com"
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
