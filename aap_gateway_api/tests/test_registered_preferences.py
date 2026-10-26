"""Tests for preferences registered by aap_gateway_api.registered_preferences."""

import pytest
from ansible_base.authentication.jwk_client import DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS, MAX_JWKS_REFRESH_COOLDOWN_SECONDS
from ansible_base.lib.utils.response import get_relative_url
from rest_framework import status

from aap_gateway_api.preferences.registry import gateway_preference_registry


class TestJWKSRefreshCooldownPreference:
    """Tests for the configurable forced JWKS refresh cooldown."""

    section = "authentication"
    name = "jwks_refresh_cooldown_seconds"

    def test_preference_is_registered_with_safe_bounds(self):
        preference = gateway_preference_registry.get(self.name, self.section)

        assert preference.default == DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS
        assert preference.min_value == 0
        assert preference.max_value == MAX_JWKS_REFRESH_COOLDOWN_SECONDS

    @pytest.mark.parametrize("value", [0, DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS, MAX_JWKS_REFRESH_COOLDOWN_SECONDS])
    def test_preference_accepts_supported_values(self, admin_api_client, preference_manager, value):
        url = get_relative_url("setting-section-list", kwargs={"category_slug": self.section})

        response = admin_api_client.put(url, {self.name: value}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert admin_api_client.get(url).data[self.name] == value

    @pytest.mark.parametrize("value", [-1, MAX_JWKS_REFRESH_COOLDOWN_SECONDS + 1])
    def test_preference_rejects_values_outside_its_bounds(self, admin_api_client, preference_manager, value):
        url = get_relative_url("setting-section-list", kwargs={"category_slug": self.section})

        response = admin_api_client.put(url, {self.name: value}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
