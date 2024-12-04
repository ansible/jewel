import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.core.cache import cache
from django.test import override_settings
from flags.state import flag_enabled

from aap_gateway_api import settings


@pytest.mark.django_db
class TestConditionImplementation:
    """Test custom condition implementation and behavior"""

    def test_custom_condition_value_validation(self, admin_api_client):
        """Test custom condition correctly validates its value"""
        test_settings = {'CUSTOM_FLAG': [{'condition': 'custom', 'value': {'key': 'value'}}]}  # Custom condition  # Complex value

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert not flag_enabled('CUSTOM_FLAG', request=response.wsgi_request)

    def test_condition_without_value(self, admin_api_client):
        """Test condition behavior when value is None or empty"""
        test_settings = {'EMPTY_VALUE_FLAG': [{'condition': 'boolean', 'value': None}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            # Assert the flag is not enabled when value is None
            assert not flag_enabled('EMPTY_VALUE_FLAG', request=response.wsgi_request)


@pytest.mark.django_db
class TestRequestContext:
    """Test flag behavior with different request contexts"""

    def test_request_middleware_attributes(self, admin_api_client):
        """Test flag evaluation with middleware-added request attributes"""
        test_settings = {'MIDDLEWARE_FLAG': [{'condition': 'parameter', 'name': 'custom_attr', 'value': 'test_value'}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings, MIDDLEWARE=['flags.middleware.FlagConditionsMiddleware', *settings.MIDDLEWARE]):
            response = admin_api_client.get(url)
            assert flag_enabled('MIDDLEWARE_FLAG', request=response.wsgi_request) is False

    def test_missing_request_object(self):
        """Test flag behavior when request object is missing"""
        test_settings = {'NO_REQUEST_FLAG': [{'condition': 'boolean', 'value': True}]}

        with override_settings(FLAGS=test_settings):
            # Test without request object
            assert flag_enabled('NO_REQUEST_FLAG')


@pytest.mark.django_db
class TestCacheBehavior:
    """Test caching behavior of flags"""

    def test_cache_key_uniqueness(self, admin_api_client):
        """Test that different flags get different cache keys"""
        test_settings = {'FLAG_1': [{'condition': 'boolean', 'value': True}], 'FLAG_2': [{'condition': 'boolean', 'value': False}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert flag_enabled('FLAG_1', request=response.wsgi_request)
            assert not flag_enabled('FLAG_2', request=response.wsgi_request)

    def test_cache_expiry(self, admin_api_client):
        """Test cache expiration behavior"""
        test_settings = {'EXPIRING_FLAG': [{'condition': 'boolean', 'value': True}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            # Initial request sets cache
            response = admin_api_client.get(url)
            assert flag_enabled('EXPIRING_FLAG', request=response.wsgi_request)

            # Clear cache to simulate expiration
            cache.clear()

            # Should re-fetch from settings
            response = admin_api_client.get(url)
            assert flag_enabled('EXPIRING_FLAG', request=response.wsgi_request)


@pytest.mark.django_db
class TestErrorHandling:
    """Test error handling in flag evaluation"""

    def test_malformed_condition(self, admin_api_client):
        """Test handling of malformed condition dictionary"""
        test_settings = {'MALFORMED_FLAG': [{'value': True}]}  # Missing condition key

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            with pytest.raises(KeyError):
                response = admin_api_client.get(url)
                flag_enabled('MALFORMED_FLAG', request=response.wsgi_request)

    def test_unknown_condition_type(self, admin_api_client):
        """Test handling of unknown condition type"""
        test_settings = {'UNKNOWN_CONDITION_FLAG': [{'condition': 'nonexistent_condition', 'value': True}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert not flag_enabled('UNKNOWN_CONDITION_FLAG', request=response.wsgi_request)

    def test_condition_without_value(self, admin_api_client):
        """Test condition behavior when value is None or empty"""
        test_settings = {'EMPTY_VALUE_FLAG': [{'condition': 'boolean', 'value': None}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert not flag_enabled('EMPTY_VALUE_FLAG', request=response.wsgi_request)


@pytest.mark.django_db
class TestFeatureCondition:
    """Test feature condition behavior"""

    def test_basic_feature_condition(self, admin_api_client):
        """Test basic feature condition evaluation"""
        test_settings = {'BASE_FLAG': [{'condition': 'boolean', 'value': True}], 'DEPENDENT_FLAG': [{'condition': 'feature', 'value': 'BASE_FLAG'}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert flag_enabled('DEPENDENT_FLAG', request=response.wsgi_request)

    def test_feature_condition_with_disabled_base(self, admin_api_client):
        """Test feature condition when base feature is disabled"""
        test_settings = {'BASE_FLAG': [{'condition': 'boolean', 'value': False}], 'DEPENDENT_FLAG': [{'condition': 'feature', 'value': 'BASE_FLAG'}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert not flag_enabled('DEPENDENT_FLAG', request=response.wsgi_request)

    def test_feature_condition_with_nonexistent_base(self, admin_api_client):
        """Test feature condition with non-existent base flag"""
        test_settings = {'DEPENDENT_FLAG': [{'condition': 'feature', 'value': 'NONEXISTENT_FLAG'}]}

        url = get_relative_url('ping-view')
        with override_settings(FLAGS=test_settings):
            response = admin_api_client.get(url)
            assert not flag_enabled('DEPENDENT_FLAG', request=response.wsgi_request)
