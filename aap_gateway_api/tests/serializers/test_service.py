from ansible_base.lib.utils.response import get_relative_url
from rest_framework import status


class TestServiceAPIRouteSerializer:
    def test_no_gateway_auth_internal_route(self, admin_api_client, service_api_route_gateway):
        url = get_relative_url('service-detail', kwargs={'pk': service_api_route_gateway.id})
        payload = {'is_internal_route': True, 'enable_gateway_auth': False}

        response = admin_api_client.patch(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is_internal_route" in response.data

    def test_disable_gateway_auth_and_internal_route_separately(self, admin_api_client, service_api_route_gateway):
        url = get_relative_url('service-detail', kwargs={'pk': service_api_route_gateway.id})
        payload = {'enable_gateway_auth': False}

        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK

        payload["is_internal_route"] = True
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is_internal_route" in response.data

    def test_gateway_auth_with_enable_mtls(self, admin_api_client, service_api_route_gateway):
        url = get_relative_url('service-detail', kwargs={'pk': service_api_route_gateway.id})

        payload = {'enable_mtls': True, 'enable_gateway_auth': True}
        response = admin_api_client.patch(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "enable_mtls" in response.data

        payload = {'enable_mtls': True, 'enable_gateway_auth': False}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK


class TestAdditionalRouteSerializer:
    def test_no_gateway_auth_internal_route(self, admin_api_client, additional_route_gateway):
        url = get_relative_url('route-detail', kwargs={'pk': additional_route_gateway.id})
        payload = {'is_internal_route': True, 'enable_gateway_auth': False}

        response = admin_api_client.patch(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is_internal_route" in response.data

    def test_disable_gateway_auth_and_internal_route_separately(self, admin_api_client, additional_route_gateway):
        url = get_relative_url('route-detail', kwargs={'pk': additional_route_gateway.id})
        payload = {'enable_gateway_auth': False}

        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK

        payload["is_internal_route"] = True
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is_internal_route" in response.data
