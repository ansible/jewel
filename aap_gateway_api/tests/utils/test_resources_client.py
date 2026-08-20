from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest
from requests.exceptions import Timeout


def _mock_pref_value(section, name):
    if name == 'gateway_token_name':
        return 'gateway-jwt'
    return 30


@pytest.fixture
def _mock_deps():
    """Patch external dependencies needed to instantiate AllServicesClient."""
    with (
        mock.patch(
            'aap_gateway_api.utils.resources_client.get_preference_value',
            side_effect=_mock_pref_value,
        ),
        mock.patch('aap_gateway_api.utils.resources_client.to_python_boolean', return_value=False),
        mock.patch('aap_gateway_api.utils.resources_client.get_user_model') as mock_user_model,
    ):
        mock_user_model.return_value.objects.filter.return_value.first.return_value = mock.MagicMock()
        yield


@pytest.fixture
def client(_mock_deps):
    """Create an AllServicesClient with mocked dependencies."""
    from aap_gateway_api.utils.resources_client import AllServicesClient

    return AllServicesClient(user=mock.MagicMock(), wait_for_response=False)


@pytest.fixture
def sync_client(_mock_deps):
    """Create an AllServicesClient with wait_for_response=True."""
    from aap_gateway_api.utils.resources_client import AllServicesClient

    return AllServicesClient(user=mock.MagicMock(), wait_for_response=True)


@pytest.fixture
def mock_service():
    """Create a mock service for testing."""
    service = mock.MagicMock()
    service.pk = 1
    service.http_port.use_https = False
    service.http_port.number = 8080
    service.gateway_path = '/api'
    service.service_cluster.service_type.service_index_path = '/v2/'
    return service


@pytest.fixture
def mock_services():
    """Create a list of mock services."""
    services = []
    for i in range(3):
        svc = mock.MagicMock()
        svc.pk = i + 1
        svc.http_port.use_https = False
        svc.http_port.number = 8080 + i
        svc.gateway_path = '/api'
        svc.service_cluster.service_type.service_index_path = '/v2/'
        services.append(svc)
    return services


class TestMakeServiceRequest:
    """Tests for _make_service_request (the single-service HTTP call)."""

    def test_timeout_uses_logger_error(self, client, mock_service):
        """Timeout logs error (not exception) when wait_for_response=False."""
        with (
            mock.patch('aap_gateway_api.utils.resources_client.requests.request', side_effect=Timeout("timed out")),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            client._make_service_request(mock_service, 'GET', '/test/', jwt='fake-jwt')

            mock_logger.error.assert_called_once()
            assert 'Resource client request timeout' in mock_logger.error.call_args[0][0]
            mock_logger.exception.assert_not_called()

    def test_timeout_raises_when_waiting(self, client, mock_service):
        """Timeout raises when wait_for_response=True."""
        with mock.patch('aap_gateway_api.utils.resources_client.requests.request', side_effect=Timeout("timed out")):
            client.wait_for_response = True
            with pytest.raises(Timeout):
                client._make_service_request(mock_service, 'GET', '/test/', jwt='fake-jwt')

    def test_successful_request_returns_response(self, client, mock_service):
        """Successful request returns (service_pk, response)."""
        mock_resp = mock.MagicMock(status_code=200)
        with mock.patch('aap_gateway_api.utils.resources_client.requests.request', return_value=mock_resp):
            pk, resp = client._make_service_request(mock_service, 'GET', '/test/', jwt='fake-jwt')
            assert pk == mock_service.pk
            assert resp.status_code == 200


class TestAsyncWorker:
    """Tests for _async_worker (background thread handler)."""

    def test_successful_request_invokes_callback(self, client, mock_service):
        """Callback receives service and response on success."""
        mock_resp = mock.MagicMock(status_code=200)
        callback = mock.MagicMock()

        with mock.patch.object(client, '_make_service_request', return_value=(mock_service.pk, mock_resp)):
            client._async_worker(mock_service, 'GET', '/test/', None, None, 'jwt', callback)

        callback.assert_called_once_with(mock_service, mock_resp)

    def test_timeout_logs_error_and_invokes_callback_with_none(self, client, mock_service):
        """Timeout is caught, logged, and callback receives None."""
        callback = mock.MagicMock()

        with (
            mock.patch.object(client, '_make_service_request', side_effect=Timeout("timed out")),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            client._async_worker(mock_service, 'GET', '/test/', None, None, 'jwt', callback)

        mock_logger.error.assert_called_once()
        callback.assert_called_once_with(mock_service, None)

    def test_exception_logs_and_invokes_callback_with_none(self, client, mock_service):
        """Generic exception is caught, logged, and callback receives None."""
        callback = mock.MagicMock()

        with (
            mock.patch.object(client, '_make_service_request', side_effect=RuntimeError("boom")),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            client._async_worker(mock_service, 'GET', '/test/', None, None, 'jwt', callback)

        mock_logger.exception.assert_called_once()
        callback.assert_called_once_with(mock_service, None)

    def test_no_callback_does_not_error(self, client, mock_service):
        """No callback is fine — just runs the request."""
        mock_resp = mock.MagicMock(status_code=200)
        with mock.patch.object(client, '_make_service_request', return_value=(mock_service.pk, mock_resp)):
            client._async_worker(mock_service, 'GET', '/test/', None, None, 'jwt', None)

    def test_callback_exception_is_logged(self, client, mock_service):
        """Callback exception is caught and logged, not propagated."""
        mock_resp = mock.MagicMock(status_code=200)
        callback = mock.MagicMock(side_effect=RuntimeError("callback boom"))

        with (
            mock.patch.object(client, '_make_service_request', return_value=(mock_service.pk, mock_resp)),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            client._async_worker(mock_service, 'GET', '/test/', None, None, 'jwt', callback)

        callback.assert_called_once_with(mock_service, mock_resp)
        mock_logger.exception.assert_called_once()
        assert 'Callback failed' in mock_logger.exception.call_args[0][0]


class TestMakeAsyncRequest:
    """Tests for _make_async_request (fire-and-forget path)."""

    def test_submits_to_executor_and_returns_immediately(self, client, mock_services):
        """Each service is submitted to the lazily-initialized executor."""
        mock_executor = mock.MagicMock()
        with mock.patch('aap_gateway_api.utils.resources_client._get_executor', return_value=mock_executor):
            result = client._make_async_request(mock_services, 'DELETE', '/test/', None, None, 'jwt')

        assert result == {}
        assert mock_executor.submit.call_count == len(mock_services)
        for call in mock_executor.submit.call_args_list:
            assert call[0][0] == client._async_worker

    def test_passes_callback_to_workers(self, client, mock_services):
        """Callback is captured and passed to each worker."""
        callback = mock.MagicMock()
        client.callback = callback
        mock_executor = mock.MagicMock()

        with mock.patch('aap_gateway_api.utils.resources_client._get_executor', return_value=mock_executor):
            client._make_async_request(mock_services, 'DELETE', '/test/', None, None, 'jwt')

        for call in mock_executor.submit.call_args_list:
            assert call[0][-1] is callback

    def test_add_done_callback_attached(self, client, mock_services):
        """Each submitted future gets a done callback for error logging."""
        mock_executor = mock.MagicMock()
        mock_future = mock.MagicMock()
        mock_executor.submit.return_value = mock_future

        with mock.patch('aap_gateway_api.utils.resources_client._get_executor', return_value=mock_executor):
            client._make_async_request(mock_services, 'DELETE', '/test/', None, None, 'jwt')

        assert mock_future.add_done_callback.call_count == len(mock_services)


class TestLogAsyncResult:
    """Tests for _log_async_result (future done callback)."""

    def test_logs_exception_from_future(self):
        """Unhandled exceptions in futures are logged."""
        from aap_gateway_api.utils.resources_client import AllServicesClient

        mock_future = mock.MagicMock()
        mock_future.exception.return_value = RuntimeError("boom")

        with mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger:
            AllServicesClient._log_async_result(mock_future)

        mock_logger.exception.assert_called_once()

    def test_no_log_on_success(self):
        """No logging when future completes without error."""
        from aap_gateway_api.utils.resources_client import AllServicesClient

        mock_future = mock.MagicMock()
        mock_future.exception.return_value = None

        with mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger:
            AllServicesClient._log_async_result(mock_future)

        mock_logger.exception.assert_not_called()


class TestGetExecutor:
    """Tests for _get_executor (lazy initialization)."""

    def test_creates_executor_on_first_call(self):
        """Executor is lazily created on first call."""
        import aap_gateway_api.utils.resources_client as rc

        original = rc._fire_and_forget_executor
        try:
            rc._fire_and_forget_executor = None
            executor = rc._get_executor()
            assert isinstance(executor, ThreadPoolExecutor)
            assert rc._fire_and_forget_executor is executor
        finally:
            if rc._fire_and_forget_executor is not original:
                rc._fire_and_forget_executor.shutdown(wait=False)
            rc._fire_and_forget_executor = original

    def test_returns_same_executor_on_subsequent_calls(self):
        """Second call returns the same executor instance."""
        import aap_gateway_api.utils.resources_client as rc

        original = rc._fire_and_forget_executor
        try:
            rc._fire_and_forget_executor = None
            first = rc._get_executor()
            second = rc._get_executor()
            assert first is second
        finally:
            if rc._fire_and_forget_executor is not original:
                rc._fire_and_forget_executor.shutdown(wait=False)
            rc._fire_and_forget_executor = original


class TestMakeSynchronousRequest:
    """Tests for _make_synchronous_request (blocking path)."""

    def test_returns_responses_for_all_services(self, sync_client, mock_services):
        """All service responses are collected and returned."""
        with mock.patch.object(
            sync_client,
            '_make_service_request',
            side_effect=lambda svc, *args, **kwargs: (svc.pk, mock.MagicMock(status_code=200)),
        ):
            responses = sync_client._make_synchronous_request(mock_services, 'GET', '/test/', None, None, 'jwt')

        assert len(responses) == len(mock_services)
        for svc in mock_services:
            assert svc.pk in responses
            assert responses[svc.pk].status_code == 200

    def test_timeout_raises(self, sync_client, mock_services):
        """Timeout is re-raised in the synchronous path."""
        with mock.patch.object(sync_client, '_make_service_request', side_effect=Timeout("timed out")):
            with pytest.raises(Timeout):
                sync_client._make_synchronous_request(mock_services, 'GET', '/test/', None, None, 'jwt')

    def test_exception_logged_and_response_is_none(self, sync_client, mock_services):
        """Generic exception is caught, logged, response set to None."""
        with (
            mock.patch.object(sync_client, '_make_service_request', side_effect=RuntimeError("boom")),
            mock.patch('aap_gateway_api.utils.resources_client.logger') as mock_logger,
        ):
            responses = sync_client._make_synchronous_request(mock_services, 'GET', '/test/', None, None, 'jwt')

        assert all(r is None for r in responses.values())
        assert mock_logger.exception.call_count == len(mock_services)

    def test_callback_invoked_for_each_service(self, sync_client, mock_services):
        """Callback is called after each service response."""
        callback_calls = []
        sync_client.callback = lambda svc, resp: callback_calls.append((svc.pk, resp))

        with mock.patch.object(
            sync_client,
            '_make_service_request',
            side_effect=lambda svc, *args, **kwargs: (svc.pk, mock.MagicMock(status_code=200)),
        ):
            sync_client._make_synchronous_request(mock_services, 'GET', '/test/', None, None, 'jwt')

        assert len(callback_calls) == len(mock_services)


class TestMakeRequest:
    """Tests for _make_request (routing logic)."""

    def test_routes_to_async_when_not_waiting(self, client):
        """wait_for_response=False routes to _make_async_request."""
        with (
            mock.patch.object(client, '_get_services', return_value=[mock.MagicMock()]),
            mock.patch.object(client, '_make_async_request', return_value={}) as mock_async,
            mock.patch.object(client, '_make_synchronous_request') as mock_sync,
            mock.patch.object(type(client), 'jwt', new_callable=mock.PropertyMock, return_value='jwt'),
        ):
            client._make_request('GET', '/test/')

        mock_async.assert_called_once()
        mock_sync.assert_not_called()

    def test_routes_to_sync_when_waiting(self, sync_client):
        """wait_for_response=True routes to _make_synchronous_request."""
        with (
            mock.patch.object(sync_client, '_get_services', return_value=[mock.MagicMock()]),
            mock.patch.object(sync_client, '_make_async_request') as mock_async,
            mock.patch.object(sync_client, '_make_synchronous_request', return_value={}) as mock_sync,
            mock.patch.object(type(sync_client), 'jwt', new_callable=mock.PropertyMock, return_value='jwt'),
        ):
            sync_client._make_request('GET', '/test/')

        mock_sync.assert_called_once()
        mock_async.assert_not_called()

    def test_empty_services_returns_empty_dict(self, client):
        """No services means immediate return with empty dict."""
        with mock.patch.object(client, '_get_services', return_value=[]):
            result = client._make_request('GET', '/test/')

        assert result == {}


class TestGetServices:
    """Tests for _get_services (service discovery)."""

    def test_excludes_gateway_and_empty_index_paths(self, client):
        """Verifies the queryset excludes gateway and services without index paths."""
        mock_svc_qs = mock.MagicMock()
        mock_svc_qs.select_related.return_value = mock_svc_qs
        mock_svc_qs.exclude.return_value = mock_svc_qs

        with mock.patch('aap_gateway_api.models.ServiceAPIRoute.objects', mock_svc_qs):
            client._get_services()

        mock_svc_qs.select_related.assert_called_once()
        assert mock_svc_qs.exclude.call_count == 3

    def test_applies_service_filter(self, client):
        """service_filter kwarg is applied to the queryset."""
        client.service_filter = {"service_cluster__service_type__name": "controller"}
        mock_svc_qs = mock.MagicMock()
        mock_svc_qs.select_related.return_value = mock_svc_qs
        mock_svc_qs.exclude.return_value = mock_svc_qs
        mock_svc_qs.filter.return_value = mock_svc_qs

        with mock.patch('aap_gateway_api.models.ServiceAPIRoute.objects', mock_svc_qs):
            client._get_services()

        mock_svc_qs.filter.assert_called_once_with(service_cluster__service_type__name="controller")
