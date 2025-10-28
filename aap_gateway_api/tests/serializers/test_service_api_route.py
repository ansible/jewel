import pytest
from ansible_base.lib.utils.response import get_relative_url
from rest_framework import status

from aap_gateway_api.serializers.service_api_route import ServiceAPIRouteSerializer


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

    # Note: gateway_path is read-only in the API, so integration tests
    # via API calls are not applicable. The double slash removal is tested
    # in the unit tests below.

    @pytest.mark.parametrize(
        "input_path,expected_path",
        [
            ('/api//my-service//path', '/api/my-service/path'),
            ('////', '/'),
        ],
    )
    def test_gateway_path_normalization_integration(self, input_path, expected_path):
        """
        Integration test verifying that ServiceAPIRouteSerializer applies path normalization.

        This ensures the serializer correctly calls remove_multiple_slashes_from_path().
        Comprehensive path normalization tests are in tests/utils/test_urls.py.
        """
        test_data = {'gateway_path': input_path, 'enable_gateway_auth': True, 'is_internal_route': False}
        serializer = ServiceAPIRouteSerializer()
        validated_data = serializer.validate(test_data)
        assert validated_data['gateway_path'] == expected_path
