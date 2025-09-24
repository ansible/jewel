import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.test import override_settings
from flags.state import flag_enabled


@pytest.fixture(autouse=True)
def clear_cache(isolated_cache):
    """Clear cache before and after each test with worker isolation"""
    isolated_cache.clear()
    yield
    isolated_cache.clear()


@pytest.mark.django_db
class TestFeatureFlagParameters:
    """Test feature flag parameter conditions"""

    def test_parameter_flag_basic(self, admin_api_client, isolated_cache):
        """Test basic parameter flag behavior"""
        url = get_relative_url('ping-view')

        test_settings = {'TEST_FLAG': [{'condition': 'parameter', 'name': 'foo', 'value': 'foo=bar'}]}

        with override_settings(FLAGS=test_settings):
            # Test without parameter
            isolated_cache.clear()
            response = admin_api_client.get(url)
            assert not flag_enabled('TEST_FLAG', request=response.wsgi_request), "Flag should be disabled without parameter"

            # Test with correct parameter
            isolated_cache.clear()
            url_with_param = f"{url}?foo=bar"
            response = admin_api_client.get(url_with_param)
            assert flag_enabled('TEST_FLAG', request=response.wsgi_request), "Flag should be enabled with correct parameter"

            # Test with wrong value
            isolated_cache.clear()
            response = admin_api_client.get(f"{url}?foo=wrong")
            assert not flag_enabled('TEST_FLAG', request=response.wsgi_request), "Flag should be disabled with wrong parameter value"

    def test_flag_state_change(self, admin_api_client, isolated_cache):
        """Test changing flag state during runtime"""
        url = get_relative_url('ping-view')

        # Start with flag disabled
        with override_settings(FLAGS={'TRANSITION_FLAG': [{'condition': 'boolean', 'value': False}]}):
            response = admin_api_client.get(url)
            assert not flag_enabled('TRANSITION_FLAG', request=response.wsgi_request)

        # Change to enabled
        with override_settings(FLAGS={'TRANSITION_FLAG': [{'condition': 'boolean', 'value': True}]}):
            isolated_cache.clear()  # Clear cache to ensure new settings are picked up
            response = admin_api_client.get(url)
            assert flag_enabled('TRANSITION_FLAG', request=response.wsgi_request)


@pytest.mark.django_db
class TestFeatureFlagViews:
    """Test feature flag integration with views"""

    @pytest.fixture
    def ping_url(self):
        """Get URL for ping view which we know exists"""
        return get_relative_url('ping-view')

    def test_flag_based_view_response(self, admin_api_client, ping_url, isolated_cache):
        """Test view response based on feature flag state"""
        test_settings = {'TEST_FLAG': [{'condition': 'boolean', 'value': True}]}

        with override_settings(FLAGS=test_settings):
            isolated_cache.clear()
            response = admin_api_client.get(ping_url)
            assert response.status_code == 200
            assert 'pong' in response.data
            assert flag_enabled('TEST_FLAG', request=response.wsgi_request)

    def test_flag_based_view_disabled(self, admin_api_client, ping_url, isolated_cache):
        """Test view response when feature flag is disabled"""
        test_settings = {'TEST_FLAG': [{'condition': 'boolean', 'value': False}]}

        with override_settings(FLAGS=test_settings):
            isolated_cache.clear()
            response = admin_api_client.get(ping_url)
            assert response.status_code == 200
            assert not flag_enabled('TEST_FLAG', request=response.wsgi_request)

    def test_feature_dependency_chain(self, admin_api_client, ping_url, isolated_cache):
        """Test that feature dependencies work correctly"""
        test_settings = {
            'PARENT_FLAG': [{'condition': 'boolean', 'value': False}],
            'CHILD_FLAG': [{'condition': 'feature', 'value': 'PARENT_FLAG', 'required': True}],
        }

        with override_settings(FLAGS=test_settings):
            isolated_cache.clear()
            response = admin_api_client.get(ping_url)
            assert response.status_code == 200
            assert not flag_enabled('PARENT_FLAG', request=response.wsgi_request)
            assert not flag_enabled('CHILD_FLAG', request=response.wsgi_request)
