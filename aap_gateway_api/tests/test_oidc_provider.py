from unittest.mock import patch

import pytest
from ansible_base.lib.utils.response import get_relative_url
from rest_framework import status

from aap_gateway_api.oidc_provider import OIDC_JWT_TTL_CLOCK_SKEW_SECONDS, LazyPrivateKey
from aap_gateway_api.registered_preferences import get_jwt_ttl_with_skew


class TestClockSkewConstant:
    """Tests for OIDC_JWT_TTL_CLOCK_SKEW_SECONDS constant"""

    def test_clock_skew_constant_value(self):
        """Verify OIDC_JWT_TTL_CLOCK_SKEW_SECONDS = 60"""
        assert OIDC_JWT_TTL_CLOCK_SKEW_SECONDS == 60

    def test_clock_skew_constant_type(self):
        """Verify constant is an integer"""
        assert isinstance(OIDC_JWT_TTL_CLOCK_SKEW_SECONDS, int)


class TestJWTTTLWithSkewHelper:
    """Tests for get_jwt_ttl_with_skew() helper function"""

    def test_helper_adds_clock_skew(self):
        """Verify helper function adds 60s clock skew to base TTL"""
        base_ttl = 300
        result = get_jwt_ttl_with_skew(base_ttl)
        assert result == 360  # 300 + 60

    def test_helper_works_with_zero(self):
        """Verify helper works with 0 TTL (returns just clock skew)"""
        result = get_jwt_ttl_with_skew(0)
        assert result == 60

    def test_helper_works_with_large_values(self):
        """Verify helper works with large TTL values"""
        result = get_jwt_ttl_with_skew(7200)  # 2 hours
        assert result == 7260  # 2 hours + 60s


def test_lazy_private_key_encode():
    mock_key = 'mock_rsa_private_key'

    with patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key', return_value=mock_key):
        lazy_key = LazyPrivateKey()
        result = lazy_key.encode('utf-8')
        assert result == mock_key.encode('utf-8')


def test_lazy_private_key_encode_handles_none():
    with patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key', return_value=None):
        lazy_key = LazyPrivateKey()
        with pytest.raises(AttributeError):
            lazy_key.encode('utf-8')


class TestJwtDefaultTtlPreference:
    """Tests for jwt_default_ttl_seconds preference"""

    def test_preference_registered(self):
        """Verify jwt_default_ttl_seconds preference is registered in 'workload_identity' section"""
        from aap_gateway_api.utils import get_preference_sections

        sections = get_preference_sections()
        assert 'workload_identity' in sections, "Workload identity section should be registered"

    def test_preference_rejects_non_integer(self, admin_api_client, preference_manager):
        """Verify preference rejects non-integer values"""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'workload_identity'})
        response = admin_api_client.put(url, {'jwt_default_ttl_seconds': 'not_an_int'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_preference_help_text_includes_guidance(self):
        """Verify help text includes guidance about clock skew, defaults, and no maximum"""
        from aap_gateway_api.preferences.registry import gateway_preference_registry

        # Find the jwt_default_ttl_seconds preference
        preference = None
        for pref in gateway_preference_registry.preferences('workload_identity'):
            if pref.name == 'jwt_default_ttl_seconds':
                preference = pref
                break

        assert preference is not None, "jwt_default_ttl_seconds preference should exist"

        help_text = preference.help_text.lower()
        assert '300' in help_text or 'five minute' in help_text, "Help text should mention default"
        assert '60' in help_text or 'clock skew' in help_text, "Help text should mention clock skew offset"
        assert 'no hard maximum' in help_text or 'no maximum' in help_text, "Help text should mention no maximum"

    def test_preference_label(self):
        """Verify preference has user-friendly label"""
        from aap_gateway_api.preferences.registry import gateway_preference_registry

        preference = None
        for pref in gateway_preference_registry.preferences('workload_identity'):
            if pref.name == 'jwt_default_ttl_seconds':
                preference = pref
                break

        assert preference is not None
        assert preference.label is not None
        assert 'jwt' in preference.label.lower() or 'ttl' in preference.label.lower()


class TestJwtDefaultTtlPreferenceAPI:
    """Tests for jwt_default_ttl_seconds preference via Settings API"""

    def test_preference_configurable_via_settings_api(self, admin_api_client):
        """Verify preference can be read via GET /api/gateway/v1/settings/"""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'workload_identity'})
        response = admin_api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'jwt_default_ttl_seconds' in response.data

    def test_preference_update_via_settings_api(self, admin_api_client, preference_manager):
        """Verify preference can be updated via PUT /api/gateway/v1/settings/"""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'workload_identity'})

        # Update to 600 seconds
        response = admin_api_client.put(url, {'jwt_default_ttl_seconds': 600}, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Verify update
        response = admin_api_client.get(url)
        assert response.data['jwt_default_ttl_seconds'] == 600

    def test_preference_visible_in_settings_list(self, admin_api_client):
        """Verify preference is visible in settings endpoint"""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
        response = admin_api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'jwt_default_ttl_seconds' in response.data

    def test_preference_displays_help_text(self, admin_api_client):
        """Verify help text is available through API (for UI display)"""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'workload_identity'})
        response = admin_api_client.options(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'actions' in response.data
        put_fields = response.data.get('actions', {}).get('PUT', {})
        assert 'jwt_default_ttl_seconds' in put_fields
        assert 'help_text' in put_fields['jwt_default_ttl_seconds']


class TestTTLConfigurationIntegration:
    """Integration tests for TTL configuration"""

    def test_helper_function_with_preference_default(self):
        """Verify helper function works with preference default value"""
        from aap_gateway_api.preferences.registry import gateway_preference_registry

        # Get fallback TTL from the preference registry
        preference = None
        for pref in gateway_preference_registry.preferences('workload_identity'):
            if pref.name == 'jwt_default_ttl_seconds':
                preference = pref
                break
        assert preference is not None

        # Use helper function (recommended approach)
        calculated_ttl = get_jwt_ttl_with_skew(preference.default)

        assert calculated_ttl == 360  # 300 + 60

    def test_constant_and_preference_work_together(self):
        """Verify constant and preference can be imported and used together (manual approach)"""
        from aap_gateway_api.preferences.registry import gateway_preference_registry

        clock_skew = OIDC_JWT_TTL_CLOCK_SKEW_SECONDS

        # Get fallback TTL from the preference registry
        preference = None
        for pref in gateway_preference_registry.preferences('workload_identity'):
            if pref.name == 'jwt_default_ttl_seconds':
                preference = pref
                break
        assert preference is not None
        fallback_ttl = preference.default

        # Manual calculation (alternative to using helper function)
        calculated_ttl = fallback_ttl + clock_skew

        assert calculated_ttl == 360  # 300 + 60
