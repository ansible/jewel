from unittest import mock

import pytest
from requests.exceptions import Timeout


def _mock_pref_value(section, name):
    if name == 'gateway_token_name':
        return 'gateway-jwt'
    return 30


class TestMakeServiceRequestLogging:
    """Test that _make_service_request uses logger.exception for Timeout errors."""

    @pytest.fixture
    def client(self):
        """Create an AllServicesClient with mocked dependencies."""
        with (
            mock.patch(
                'aap_gateway_api.utils.resources_client.get_preference_value',
                side_effect=_mock_pref_value,
            ),
            mock.patch('aap_gateway_api.utils.resources_client.to_python_boolean', return_value=False),
            mock.patch('aap_gateway_api.utils.resources_client.get_user_model') as mock_user_model,
        ):
            mock_user_model.return_value.objects.filter.return_value.first.return_value = mock.MagicMock()
            from aap_gateway_api.utils.resources_client import AllServicesClient

            client = AllServicesClient(user=mock.MagicMock(), wait_for_response=False)
            return client

    @pytest.fixture
    def mock_service(self):
        """Create a mock service for testing."""
        service = mock.MagicMock()
        service.pk = 1
        service.http_port.use_https = False
        service.http_port.number = 8080
        service.gateway_path = '/api'
        service.service_cluster.service_type.service_index_path = '/v2/'
        return service

    def test_make_service_request_timeout_uses_logger_exception(self, client, mock_service):
        """Verify that _make_service_request calls logger.exception (not logger.error) on Timeout."""
        with (
            mock.patch('aap_gateway_api.utils.resources_client.requests.request', side_effect=Timeout("connection timed out")),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            client.wait_for_response = False
            client._make_service_request(mock_service, 'GET', '/test/', jwt='fake-jwt')

            mock_logger.exception.assert_called_once()
            call_args = mock_logger.exception.call_args[0][0]
            assert 'Resource client request timeout' in call_args
            mock_logger.error.assert_not_called()

    def test_make_service_request_timeout_raises_when_waiting(self, client, mock_service):
        """Verify that _make_service_request raises Timeout when wait_for_response is True."""
        with mock.patch('aap_gateway_api.utils.resources_client.requests.request', side_effect=Timeout("connection timed out")):
            client.wait_for_response = True
            with pytest.raises(Timeout):
                client._make_service_request(mock_service, 'GET', '/test/', jwt='fake-jwt')


class TestMakeRequestTimeoutLogging:
    """Test that _make_request uses logger.exception for Timeout errors in the futures loop."""

    def test_future_timeout_uses_logger_exception(self):
        """Verify that the _make_request future handler calls logger.exception on Timeout."""
        with (
            mock.patch(
                'aap_gateway_api.utils.resources_client.get_preference_value',
                side_effect=_mock_pref_value,
            ),
            mock.patch('aap_gateway_api.utils.resources_client.to_python_boolean', return_value=False),
            mock.patch('aap_gateway_api.utils.resources_client.get_user_model') as mock_user_model,
        ):
            mock_user_model.return_value.objects.filter.return_value.first.return_value = mock.MagicMock()
            from aap_gateway_api.utils.resources_client import AllServicesClient

            client = AllServicesClient(user=mock.MagicMock(), wait_for_response=False)

        mock_service = mock.MagicMock()
        mock_service.pk = 42

        mock_svc_qs = mock.MagicMock()
        mock_svc_qs.exclude.return_value = mock_svc_qs
        mock_svc_qs.filter.return_value = mock_svc_qs
        mock_svc_qs.__iter__ = mock.MagicMock(return_value=iter([mock_service]))

        with (
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
            mock.patch.object(client, '_make_service_request', side_effect=Timeout("timed out")),
            mock.patch.object(type(client), 'jwt', new_callable=mock.PropertyMock, return_value='fake-jwt'),
            mock.patch('aap_gateway_api.models.ServiceAPIRoute.objects', mock_svc_qs),
        ):
            responses = client._make_request('GET', '/test/')

            mock_logger.exception.assert_called_once()
            call_args = mock_logger.exception.call_args[0][0]
            assert 'Resource client request timeout for service 42' in call_args
            mock_logger.error.assert_not_called()
            assert responses[42] is None
