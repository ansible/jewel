"""Tests verifying CleanTextMixin integration with settings preferences.

Covers the PlainSerializerCleanTextMixin wired into SettingSectionSerializer
and the OPTIONS pattern injection in SettingsPreferenceMetadata.

The validation is gated behind ENHANCED_INPUT_VALIDATION_ENABLED, so all
tests use the enable_enhanced_validation fixture to enable it.
"""

import pytest
from ansible_base.lib.utils.response import get_relative_url

DANGEROUS_SCRIPT = '<script>alert(1)</script>'
DANGEROUS_SHELL = '$(rm -rf /)'


@pytest.fixture(autouse=True)
def enable_enhanced_validation(settings):
    """Enable enhanced input validation for all tests in this module."""
    settings.ENHANCED_INPUT_VALIDATION_ENABLED = True


# ---------------------------------------------------------------------------
# 1. Unsafe string preference rejected with 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUnsafeStringPreferenceRejected:
    """PUT with a dangerous string value in a text preference must return 400."""

    @pytest.mark.parametrize(
        "bad_value",
        [
            DANGEROUS_SCRIPT,
            DANGEROUS_SHELL,
        ],
        ids=["html_script_tag", "shell_injection"],
    )
    def test_rejects_unsafe_string_preference(self, admin_api_client, register_preference, bad_value):
        register_preference(
            section="cleantext_test",
            preference_name="test_string_pref",
            default="safe default",
            preference_type="string",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.put(url, {'test_string_pref': bad_value}, format='json')
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert 'test_string_pref' in response.data

    def test_accepts_safe_string_preference(self, admin_api_client, register_preference):
        """PUT with a safe string value should succeed."""
        register_preference(
            section="cleantext_test",
            preference_name="test_string_pref",
            default="safe default",
            preference_type="string",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.put(url, {'test_string_pref': 'updated safe value'}, format='json')
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Unsafe string list item rejected with 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUnsafeStringListItemRejected:
    """PUT with a dangerous string inside a list preference must return 400."""

    def test_rejects_unsafe_list_item(self, admin_api_client, register_preference):
        register_preference(
            section="cleantext_test",
            preference_name="test_list_pref",
            default=[],
            preference_type="string_list",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.put(
            url,
            {'test_list_pref': ['https://safe.example.com', DANGEROUS_SCRIPT]},
            format='json',
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert 'test_list_pref' in response.data

    def test_accepts_safe_list_items(self, admin_api_client, register_preference):
        """PUT with a list of safe strings should succeed."""
        register_preference(
            section="cleantext_test",
            preference_name="test_list_pref",
            default=[],
            preference_type="string_list",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.put(
            url,
            {'test_list_pref': ['https://safe.example.com', 'https://other.example.com']},
            format='json',
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 3. custom_login_info HTML allowed (excluded field)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCustomLoginInfoHtmlAllowed:
    """custom_login_info legitimately contains HTML and must be excluded from validation."""

    def test_custom_login_info_accepts_html(self, admin_api_client):
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'local_login'})
        html_content = '<p>Welcome to <strong>Our Platform</strong>. Please read the <a href="/tos">Terms</a>.</p>'
        response = admin_api_client.put(url, {'custom_login_info': html_content}, format='json')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"


# ---------------------------------------------------------------------------
# 4. Encrypted preferences unchanged (skip validation)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEncryptedPreferencesUnchanged:
    """Encrypted preference values must not be passed through text validation."""

    def test_encrypted_pref_skipped_by_clean_text(self, admin_api_client, register_preference):
        """An encrypted preference whose value looks 'dangerous' should still be accepted,
        because encrypted fields are excluded from CleanText validation."""
        register_preference(
            section="cleantext_test",
            preference_name="test_encrypted_pref",
            default="safe_default",
            preference_type="string",
            encrypted=True,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        # Pass a value that would fail Tier 2 validation if it were checked
        response = admin_api_client.put(url, {'test_encrypted_pref': DANGEROUS_SHELL}, format='json')
        assert response.status_code == 200, f"Expected 200 (encrypted skip), got {response.status_code}: {response.data}"


# ---------------------------------------------------------------------------
# 5. OPTIONS pattern present/absent correctly, no 500
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOptionsPatternBehavior:
    """OPTIONS response must include pattern metadata for text fields when enabled."""

    def test_options_has_pattern_for_string_field(self, admin_api_client, register_preference):
        """A string preference should have pattern/patternDescription/flags in OPTIONS."""
        register_preference(
            section="cleantext_test",
            preference_name="test_pattern_pref",
            default="default",
            preference_type="string",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.options(url)
        assert response.status_code == 200, f"OPTIONS returned {response.status_code}"
        put_fields = response.data.get('actions', {}).get('PUT', {})
        field_info = put_fields.get('test_pattern_pref', {})
        assert 'pattern' in field_info, f"Expected 'pattern' in field info, got keys: {list(field_info.keys())}"
        assert 'patternDescription' in field_info
        assert 'flags' in field_info
        assert field_info['flags'] == 'i'

    def test_options_no_pattern_when_disabled(self, admin_api_client, settings, register_preference):
        """When ENHANCED_INPUT_VALIDATION_ENABLED is False, no pattern should appear."""
        settings.ENHANCED_INPUT_VALIDATION_ENABLED = False

        register_preference(
            section="cleantext_test",
            preference_name="test_pattern_pref",
            default="default",
            preference_type="string",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.options(url)
        assert response.status_code == 200
        put_fields = response.data.get('actions', {}).get('PUT', {})
        field_info = put_fields.get('test_pattern_pref', {})
        assert 'pattern' not in field_info

    def test_options_no_pattern_for_int_field(self, admin_api_client, register_preference):
        """Integer preferences should not have validation patterns."""
        register_preference(
            section="cleantext_test",
            preference_name="test_int_pref",
            default=42,
            preference_type="int",
            encrypted=False,
        )

        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'cleantext_test'})
        response = admin_api_client.options(url)
        assert response.status_code == 200
        put_fields = response.data.get('actions', {}).get('PUT', {})
        field_info = put_fields.get('test_int_pref', {})
        assert 'pattern' not in field_info

    def test_options_no_pattern_for_excluded_field(self, admin_api_client):
        """custom_login_info is excluded and should not have a pattern."""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'local_login'})
        response = admin_api_client.options(url)
        assert response.status_code == 200
        put_fields = response.data.get('actions', {}).get('PUT', {})
        login_info = put_fields.get('custom_login_info', {})
        assert 'pattern' not in login_info

    def test_options_no_500_on_all_settings(self, admin_api_client):
        """OPTIONS on /settings/all/ must not crash (no 500)."""
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
        response = admin_api_client.options(url)
        assert response.status_code == 200, f"OPTIONS /settings/all/ returned {response.status_code}"
        assert 'actions' in response.data
