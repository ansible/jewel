import pytest

from aap_gateway_api.models import AdditionalRoute, DefaultServiceType, ServiceAPIRoute, ServiceCluster, ServiceType


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
    def test_xds_route_config_missing_data(self):
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
        routes = route.get_xds_route_config()
        assert len(routes) == 1

    @pytest.mark.django_db
    def test_xds_route_config_paths_equal(self):
        route = ServiceAPIRoute(gateway_path='/', service_path='/', envoy_cluster_name='testing')
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'filter_metadata' not in routes[0]["metadata"]
        assert 'envoy.filters.http.lua' not in routes[0]["typed_per_filter_config"]

    @pytest.mark.django_db
    def test_xds_route_config_paths_different(self):
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing')
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'filter_metadata' in routes[0]["metadata"]
        assert 'envoy.filters.http.lua' in routes[0]["typed_per_filter_config"]

    @pytest.mark.django_db
    def test_xds_route_config_enable_gateway_auth(self):
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=True)
        routes = route.get_xds_route_config()
        assert len(routes) == 1
        assert 'envoy.filters.http.ext_authz' not in routes[0]["typed_per_filter_config"]

    @pytest.mark.django_db
    def test_xds_route_config_disable_gateway_auth(self):
        route = ServiceAPIRoute(gateway_path='/', service_path='/path', envoy_cluster_name='testing', enable_gateway_auth=False)
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
