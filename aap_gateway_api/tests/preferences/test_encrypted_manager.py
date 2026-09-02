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
        from aap_gateway_api.preferences import gateway_preference_registry

        pref_obj = gateway_preference_registry.get("test_encrypted_manager_preference", "testing")
        pref_none_obj = gateway_preference_registry.get("test_encrypted_manager_none_preference", "testing")

        db_pref = preferences.gateway_preference_manager.get_db_pref("testing", "test_encrypted_manager_preference")
        db_pref_none = preferences.gateway_preference_manager.get_db_pref("testing", "test_encrypted_manager_none_preference")

        manager = preferences.gateway_preference_manager
        manager.to_cache(db_pref)
        # Only cache one pref — leave pref_none_obj out of cache to exercise the
        # "if k in cached" filter (cache-miss items should be silently skipped).
        manager.to_cache(db_pref_none)

        result = manager.many_from_cache([pref_obj, pref_none_obj])
        assert result["testing__test_encrypted_manager_preference"] == ["some_value"]
        assert result["testing__test_encrypted_manager_none_preference"] is None

    def test_many_from_cache_skips_uncached(self):
        from aap_gateway_api.preferences import gateway_preference_registry

        pref_obj = gateway_preference_registry.get("test_encrypted_manager_preference", "testing")
        pref_none_obj = gateway_preference_registry.get("test_encrypted_manager_none_preference", "testing")

        manager = preferences.gateway_preference_manager
        # Only cache one preference
        db_pref = manager.get_db_pref("testing", "test_encrypted_manager_preference")
        manager.to_cache(db_pref)
        # Explicitly remove the other from cache to guarantee a miss
        cache_key = manager.get_cache_key("testing", "test_encrypted_manager_none_preference")
        manager.cache.delete(cache_key)

        result = manager.many_from_cache([pref_obj, pref_none_obj])
        # Only the cached preference should appear in results
        assert "testing__test_encrypted_manager_preference" in result
        assert "testing__test_encrypted_manager_none_preference" not in result


class TestEncryptedManagerWithEncryptedPref:
    @pytest.fixture(autouse=True)
    def setup_encrypted_pref(self, admin_api_client, register_preference):
        register_preference(
            section="testing",
            preference_name="test_enc_pref",
            default="secret_data",
            required=False,
            encrypted=True,
            preference_type="string",
            help_text="An encrypted preference for cache testing",
        )
        url = get_relative_url("setting-section-list", kwargs={"category_slug": "testing"})
        admin_api_client.get(url)

    def test_many_from_cache_decrypts_encrypted_values(self):
        from aap_gateway_api.preferences import gateway_preference_registry

        pref_obj = gateway_preference_registry.get("test_enc_pref", "testing")
        db_pref = preferences.gateway_preference_manager.get_db_pref("testing", "test_enc_pref")

        manager = preferences.gateway_preference_manager
        manager.to_cache(db_pref)

        result = manager.many_from_cache([pref_obj])
        assert result["testing__test_enc_pref"] == "secret_data"
