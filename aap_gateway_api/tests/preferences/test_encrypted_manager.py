import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.utils import preferences


class TestEncryptedManager:
    @pytest.fixture(scope="function", autouse=True)
    def create_and_get_preferences_once(self, admin_api_client, register_preference):
        register_preference(
            section="testing",
            preference_name="test_encrypted_manager_preference",
            default=["some_value"],
            required=False,
            encrypted=False,
            preference_type="string_list",
            help_text="This is a test preference",
        )

        register_preference(
            section="testing",
            preference_name="test_encrypted_manager_none_preference",
            default=None,
            required=True,
            encrypted=False,
            preference_type="json",
            help_text="This is a test preference",
        )

        url = get_relative_url("setting-section-list", kwargs={"category_slug": "testing"})

        admin_api_client.get(url)

    def test_from_cache(self):
        encrypted_preference = preferences.gateway_preference_manager.get_db_pref("testing", "test_encrypted_manager_preference")
        encrypted_preference_none = preferences.gateway_preference_manager.get_db_pref("testing", "test_encrypted_manager_none_preference")

        manager = preferences.gateway_preference_manager
        manager.to_cache(encrypted_preference)
        manager.to_cache(encrypted_preference_none)

        assert manager.from_cache("testing", "test_encrypted_manager_preference") == ["some_value"]
        assert manager.from_cache("testing", "test_encrypted_manager_none_preference") is None

    def test_many_from_cache(self):
        pass
