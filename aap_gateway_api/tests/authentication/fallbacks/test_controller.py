"""
Tests for Controller fallback authentication.

This module tests the FallbackAuthenticator class which handles
authentication fallback to Controller during user migration.
"""

from unittest.mock import Mock, patch

import pytest
import requests
from django.http import HttpRequest
from django.urls import reverse

from aap_gateway_api.authentication.fallbacks.controller import FallbackAuthenticator
from aap_gateway_api.models import ServiceAPIRoute


@pytest.fixture
def fallback_authenticator():
    """Create a FallbackAuthenticator instance for testing."""
    return FallbackAuthenticator()


@pytest.fixture
def mock_request():
    """Create a mock HTTP request for testing."""
    request = Mock(spec=HttpRequest)
    request.path = reverse('login')
    return request


@pytest.fixture
def gateway_user(user):
    """Create a test user in the Gateway database with migration flag."""
    user.username = 'testuser'
    user.first_name = 'Test'
    user.last_name = 'User'
    user.email = 'test@example.com'
    user.is_superuser = False
    user.use_controller_password = True
    user.save()
    return user


@pytest.fixture
def controller_user_data():
    """Sample controller user data response."""
    return {
        'username': 'testuser',
        'first_name': 'Controller',
        'last_name': 'User',
        'email': 'controller@example.com',
        'is_superuser': True,
        'is_system_auditor': False,
        'ldap_dn': '',
        'password': '$encrypted$',
    }


@pytest.fixture
def controller_response_data(controller_user_data):
    """Sample response from Controller /me/ endpoint."""
    return {'count': 1, 'results': [controller_user_data]}


@pytest.fixture
def mock_controller_cluster(db, service_cluster_controller):
    """Create mock controller cluster and route."""
    from aap_gateway_api.models import HTTPPort

    http_port = HTTPPort.objects.create(name='api-port', number=443, is_api_port=True)
    route = ServiceAPIRoute.objects.create(
        name='Controller API Route',
        service_cluster=service_cluster_controller,
        service_port=443,
        service_path='/api/controller/',
        is_service_https=True,
        api_slug='controller',
        http_port=http_port,
    )
    return service_cluster_controller, route


class TestAuthenticate:
    """Tests for the main authenticate() method."""

    def test_authenticate_success(self, fallback_authenticator, mock_request, gateway_user, controller_response_data, mock_controller_cluster):
        """Test successful authentication and user migration."""
        with (
            patch.object(fallback_authenticator, '_should_attempt_controller_auth') as mock_should_attempt,
            patch.object(fallback_authenticator, '_get_controller_user') as mock_get_user,
        ):

            mock_should_attempt.return_value = (gateway_user, 'http://controller.example.com/api/controller/v2/me/')
            mock_get_user.return_value = controller_response_data

            result = fallback_authenticator.authenticate(mock_request, 'testuser', 'password123')

            assert result is not None
            assert result.username == 'testuser'
            # User fields are not migrated - only password is updated
            assert result.first_name == 'Test'  # Original value from gateway_user fixture
            assert result.last_name == 'User'  # Original value from gateway_user fixture
            assert result.email == 'test@example.com'  # Original value from gateway_user fixture
            assert result.use_controller_password is False
            assert result.check_password('password123') is True

    def test_authenticate_precondition_failure(self, fallback_authenticator, mock_request):
        """Test authentication fails when preconditions not met."""
        with patch.object(fallback_authenticator, '_should_attempt_controller_auth') as mock_should_attempt:
            mock_should_attempt.return_value = (None, None)

            result = fallback_authenticator.authenticate(mock_request, 'testuser', 'password123')

            assert result is None

    def test_authenticate_controller_api_failure(self, fallback_authenticator, mock_request, gateway_user):
        """Test authentication fails when Controller API call fails."""
        with (
            patch.object(fallback_authenticator, '_should_attempt_controller_auth') as mock_should_attempt,
            patch.object(fallback_authenticator, '_get_controller_user') as mock_get_user,
        ):

            mock_should_attempt.return_value = (gateway_user, 'http://controller.example.com/api/controller/v2/me/')
            mock_get_user.return_value = None

            result = fallback_authenticator.authenticate(mock_request, 'testuser', 'password123')

            assert result is None

    def test_authenticate_ldap_user_rejected(self, fallback_authenticator, mock_request, gateway_user, controller_response_data):
        """Test LDAP users are rejected."""
        # Modify the response to include LDAP DN
        controller_response_data['results'][0]['ldap_dn'] = 'cn=testuser,ou=users,dc=example,dc=com'

        with (
            patch.object(fallback_authenticator, '_should_attempt_controller_auth') as mock_should_attempt,
            patch.object(fallback_authenticator, '_get_controller_user') as mock_get_user,
        ):

            mock_should_attempt.return_value = (gateway_user, 'http://controller.example.com/api/controller/v2/me/')
            mock_get_user.return_value = controller_response_data

            result = fallback_authenticator.authenticate(mock_request, 'testuser', 'password123')

            assert result is None

    def test_authenticate_enterprise_user_rejected(self, fallback_authenticator, mock_request, gateway_user, controller_response_data):
        """Test enterprise users (non-encrypted password) are rejected."""
        # Modify the response to have non-$encrypted$ password
        controller_response_data['results'][0]['password'] = 'plaintext_or_other_value'

        with (
            patch.object(fallback_authenticator, '_should_attempt_controller_auth') as mock_should_attempt,
            patch.object(fallback_authenticator, '_get_controller_user') as mock_get_user,
        ):

            mock_should_attempt.return_value = (gateway_user, 'http://controller.example.com/api/controller/v2/me/')
            mock_get_user.return_value = controller_response_data

            result = fallback_authenticator.authenticate(mock_request, 'testuser', 'password123')

            assert result is None


class TestShouldAttemptControllerAuth:
    """Tests for _should_attempt_controller_auth() method."""

    def test_no_request_object(self, fallback_authenticator):
        """Test fails when no request object provided."""
        gateway_user, controller_url = fallback_authenticator._should_attempt_controller_auth(None, 'testuser')

        assert gateway_user is None
        assert controller_url is None

    def test_wrong_request_path(self, fallback_authenticator, gateway_user):
        """Test fails when request is not to login endpoint."""
        request = Mock(spec=HttpRequest)
        request.path = '/api/gateway/v1/some-other-endpoint/'

        gateway_user_result, controller_url = fallback_authenticator._should_attempt_controller_auth(request, 'testuser')

        assert gateway_user_result is None
        assert controller_url is None

    def test_user_does_not_exist(self, fallback_authenticator, mock_request, db):
        """Test fails when user doesn't exist in Gateway."""
        gateway_user, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'nonexistent')

        assert gateway_user is None
        assert controller_url is None

    def test_user_without_migration_flag(self, fallback_authenticator, mock_request, user):
        """Test fails when user doesn't have use_controller_password flag."""
        user.username = 'testuser'
        user.use_controller_password = False
        user.save()

        gateway_user, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'testuser')

        assert gateway_user is None
        assert controller_url is None

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    def test_no_gateway_proxy_url(self, mock_get_setting, fallback_authenticator, mock_request, gateway_user):
        """Test fails when gateway_proxy_url setting is not configured."""
        mock_get_setting.return_value = None

        gateway_user_result, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'testuser')

        assert gateway_user_result is None
        assert controller_url is None

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    @patch('aap_gateway_api.authentication.fallbacks.controller.ServiceCluster.get_cluster_by_type')
    def test_no_controller_cluster(self, mock_get_cluster, mock_get_setting, fallback_authenticator, mock_request, gateway_user):
        """Test fails when controller cluster doesn't exist."""
        mock_get_setting.return_value = 'http://proxy.example.com'
        mock_get_cluster.return_value = None

        gateway_user_result, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'testuser')

        assert gateway_user_result is None
        assert controller_url is None

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    @patch('aap_gateway_api.authentication.fallbacks.controller.ServiceCluster.get_cluster_by_type')
    @patch('aap_gateway_api.authentication.fallbacks.controller.ServiceAPIRoute.objects.filter')
    def test_no_controller_route(self, mock_filter, mock_get_cluster, mock_get_setting, fallback_authenticator, mock_request, gateway_user):
        """Test fails when controller route doesn't exist."""
        mock_get_setting.return_value = 'http://proxy.example.com'
        mock_cluster = Mock()
        mock_get_cluster.return_value = mock_cluster
        mock_filter.return_value.first.return_value = None

        gateway_user_result, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'testuser')

        assert gateway_user_result is None
        assert controller_url is None

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    def test_success_returns_user_and_url(self, mock_get_setting, fallback_authenticator, mock_request, gateway_user, mock_controller_cluster):
        """Test successful precondition check returns user and URL."""
        mock_get_setting.return_value = 'http://proxy.example.com'

        gateway_user_result, controller_url = fallback_authenticator._should_attempt_controller_auth(mock_request, 'testuser')

        assert gateway_user_result == gateway_user
        assert controller_url is not None
        assert 'controller' in controller_url
        assert '/v2/me/' in controller_url


class TestValidateControllerUserData:
    """Tests for _validate_controller_user_data() method."""

    @pytest.mark.parametrize(
        'response_data,description',
        [
            ({'count': 0, 'results': []}, 'count is 0'),
            ({'count': 2, 'results': [{}, {}]}, 'count is greater than 1'),
            ({'count': 1}, 'results field is missing'),
            ({'count': 1, 'results': []}, 'results list is empty'),
            ({'count': 1, 'results': 'not a list'}, 'results is not a list'),
            ({'count': 1, 'results': ['not a dict']}, 'first result is not a dictionary'),
        ],
    )
    def test_invalid_response_structure(self, fallback_authenticator, response_data, description):
        """Test validation fails with invalid response structure."""
        result = fallback_authenticator._validate_controller_user_data(response_data, 'testuser')

        assert result is None, f"Expected validation to fail when {description}"

    def test_valid_local_user(self, fallback_authenticator, controller_response_data):
        """Test validation succeeds with valid local user."""
        result = fallback_authenticator._validate_controller_user_data(controller_response_data, 'testuser')

        assert result is not None
        assert result['username'] == 'testuser'

    @pytest.mark.parametrize(
        'ldap_dn,description',
        [
            ('cn=testuser,ou=users,dc=example,dc=com', 'LDAP DN is set'),
            ('uid=testuser,dc=company,dc=com', 'LDAP DN with uid format'),
        ],
    )
    def test_ldap_user_rejected(self, fallback_authenticator, controller_response_data, ldap_dn, description):
        """Test LDAP users are rejected during validation."""
        controller_response_data['results'][0]['ldap_dn'] = ldap_dn

        result = fallback_authenticator._validate_controller_user_data(controller_response_data, 'testuser')

        assert result is None, f"Expected validation to fail when {description}"

    @pytest.mark.parametrize(
        'password_value,description',
        [
            ('plaintext_password', 'password is plaintext'),
            ('hashed_password', 'password is hashed'),
            (None, 'password is None'),
        ],
    )
    def test_enterprise_user_rejected(self, fallback_authenticator, controller_response_data, password_value, description):
        """Test enterprise users (non-$encrypted$ password) are rejected during validation."""
        controller_response_data['results'][0]['password'] = password_value

        result = fallback_authenticator._validate_controller_user_data(controller_response_data, 'testuser')

        assert result is None, f"Expected validation to fail when {description}"


class TestGetControllerUser:
    """Tests for _get_controller_user() method."""

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    @patch('aap_gateway_api.authentication.fallbacks.controller.convert_to_seconds')
    @patch('aap_gateway_api.authentication.fallbacks.controller.requests.get')
    def test_successful_api_call(self, mock_requests_get, mock_convert, mock_get_setting, fallback_authenticator, controller_response_data):
        """Test successful Controller API call returns raw response."""
        mock_get_setting.return_value = '30s'
        mock_convert.return_value = 30
        mock_response = Mock()
        mock_response.json.return_value = controller_response_data
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response

        result = fallback_authenticator._get_controller_user('testuser', 'password123', 'http://controller.example.com/api/v2/me/')

        assert result is not None
        assert result['count'] == 1
        assert 'results' in result
        assert len(result['results']) == 1
        assert result['results'][0]['username'] == 'testuser'
        mock_requests_get.assert_called_once()

    @pytest.mark.parametrize(
        'exception,description',
        [
            (requests.exceptions.HTTPError('401 Unauthorized'), 'HTTP error'),
            (requests.exceptions.ConnectionError('Connection refused'), 'connection error'),
            (requests.exceptions.Timeout('Request timed out'), 'timeout error'),
            (requests.exceptions.RequestException('Unknown error'), 'general request exception'),
            (Exception('Unexpected error'), 'unexpected exception'),
        ],
    )
    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    @patch('aap_gateway_api.authentication.fallbacks.controller.convert_to_seconds')
    @patch('aap_gateway_api.authentication.fallbacks.controller.requests.get')
    def test_network_errors(self, mock_requests_get, mock_convert, mock_get_setting, fallback_authenticator, exception, description):
        """Test various network and request errors during API call."""
        mock_get_setting.return_value = '30s'
        mock_convert.return_value = 30
        mock_requests_get.side_effect = exception

        result = fallback_authenticator._get_controller_user('testuser', 'password123', 'http://controller.example.com/api/v2/me/')

        assert result is None, f"Expected None when {description} occurs"

    @patch('aap_gateway_api.authentication.fallbacks.controller.get_setting')
    @patch('aap_gateway_api.authentication.fallbacks.controller.convert_to_seconds')
    @patch('aap_gateway_api.authentication.fallbacks.controller.requests.get')
    def test_json_decode_error(self, mock_requests_get, mock_convert, mock_get_setting, fallback_authenticator):
        """Test JSON decode error."""
        mock_get_setting.return_value = '30s'
        mock_convert.return_value = 30
        mock_response = Mock()
        mock_response.json.side_effect = ValueError('Invalid JSON')
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response

        result = fallback_authenticator._get_controller_user('testuser', 'password123', 'http://controller.example.com/api/v2/me/')

        assert result is None
