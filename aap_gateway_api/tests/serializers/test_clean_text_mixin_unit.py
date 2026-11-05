"""Unit tests for PlainSerializerCleanTextMixin: DAB-reuse integration and Jewel-specific logic.

These tests exercise the Jewel-specific entry points (_clean_text_validate,
_validate_field_value, _log_validation_failure override, validate() bypass)
and verify that inherited DAB CleanTextMixin helpers (JSON recursion,
depth-limiting, text validation) work correctly through the integration.

Coverage targets: type dispatch, DAB delegation (skip_keys, errors dict),
depth limits through integration, grandfathering, encrypted-field exclusion,
validate() model-path bypass, and the validate-and-save clean-text path.
"""

from unittest.mock import patch

import pytest
from ansible_base.lib.serializers.mixins import _INCOMPLETE_VALIDATION_MSG, CleanTextMixin
from rest_framework import serializers

from aap_gateway_api.serializers.preferences import PlainSerializerCleanTextMixin

# Mock target for validate_free_text — lives in DAB's mixins module
# because the inherited _run_text_validator / _validate_json_string
# call it from there.
_VFT = "ansible_base.lib.serializers.mixins.validate_free_text"
# Mock target for get_setting — DAB's methods use the DAB-side import;
# Jewel's _clean_text_validate uses the Jewel-side import.
_GS_DAB = "ansible_base.lib.serializers.mixins.get_setting"
_GS_JEWEL = "aap_gateway_api.serializers.preferences.get_setting"

# ---------------------------------------------------------------------------
# Minimal test serializer that exposes the mixin without Django models
# ---------------------------------------------------------------------------


class _TestMixinSerializer(PlainSerializerCleanTextMixin, serializers.Serializer):
    """Thin wrapper exposing the mixin for isolated testing."""

    test_field = serializers.CharField(required=False)
    test_list = serializers.ListField(required=False)
    test_json = serializers.JSONField(required=False)
    custom_login_info = serializers.CharField(required=False)


@pytest.fixture
def mixin_instance():
    """Create a fresh mixin-backed serializer for each test."""
    return _TestMixinSerializer()


# ===================================================================
# 1. Inheritance verification
# ===================================================================


class TestInheritance:
    """Verify PlainSerializerCleanTextMixin correctly inherits from DAB."""

    def test_inherits_from_clean_text_mixin(self):
        assert issubclass(PlainSerializerCleanTextMixin, CleanTextMixin)

    def test_name_fields_empty(self):
        """Preferences use Tier 2 only — no Tier 1 name-field validation."""
        assert PlainSerializerCleanTextMixin.name_fields == frozenset()

    def test_max_json_depth_inherited(self, mixin_instance):
        """_MAX_JSON_DEPTH is inherited from CleanTextMixin."""
        assert mixin_instance._MAX_JSON_DEPTH == 10


# ===================================================================
# 2. validate() bypass
# ===================================================================


class TestValidateBypass:
    """validate() must skip CleanTextMixin model-backed path."""

    def test_validate_does_not_access_meta_model(self, mixin_instance):
        """Calling validate() on a plain serializer must not crash
        due to missing Meta.model — it should reach the base
        Serializer.validate() which simply returns attrs."""
        result = mixin_instance.validate({"test_field": "value"})
        assert result == {"test_field": "value"}


# ===================================================================
# 3. _validate_field_value type dispatch
# ===================================================================


class TestValidateFieldValue:
    """_validate_field_value: routes str/list/dict to the right DAB validator."""

    @patch(_VFT)
    def test_changed_string_runs_validation(self, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "new", "old", errors)
        mock_vft.assert_called_once_with("new")

    @patch(_VFT)
    def test_unchanged_string_skipped(self, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "same", "same", errors)
        mock_vft.assert_not_called()
        assert errors == {}

    @patch(_VFT)
    def test_list_value_dispatches(self, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", ["item"], None, errors)
        mock_vft.assert_called_once_with("item")

    @patch(_VFT)
    def test_dict_value_dispatches(self, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", {"k": "v"}, None, errors)
        mock_vft.assert_called_once_with("v")

    def test_non_text_type_ignored(self, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", 42, None, errors)
        assert errors == {}
        mixin_instance._validate_field_value("f", True, None, errors)
        assert errors == {}

    @patch(_VFT, side_effect=serializers.ValidationError(["bad"]))
    def test_string_failure_collects_error(self, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "evil", "old", errors)
        assert "f" in errors

    @patch(_VFT, side_effect=serializers.ValidationError(["bad"]))
    def test_list_failure_collects_error_under_field_name(self, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("my_list", ["evil"], None, errors)
        assert "my_list" in errors

    @patch(_VFT, side_effect=serializers.ValidationError(["bad"]))
    def test_dict_failure_collects_error_under_field_name(self, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("my_dict", {"k": "evil"}, None, errors)
        assert "my_dict" in errors

    def test_over_depth_list_error_shape(self, mixin_instance):
        """Over-depth list via _validate_field_value produces the correct nested error shape."""
        data = current = []
        for _ in range(12):
            child = []
            current.append(child)
            current = child
        current.append("leaf")

        errors = {}
        mixin_instance._validate_field_value("my_list", data, None, errors)

        # The outer key is the field name.
        assert "my_list" in errors
        inner = errors["my_list"]

        # The inner dict contains a nesting-path key (not a duplicate field_name key).
        assert isinstance(inner, dict)
        assert "my_list" not in inner, "depth-limit error must not double-nest under field_name"

        # Exactly one path key carrying the incomplete-validation message.
        assert len(inner) == 1
        path_key = next(iter(inner))
        assert inner[path_key] == [_INCOMPLETE_VALIDATION_MSG]

    def test_over_depth_dict_error_shape(self, mixin_instance):
        """Over-depth dict via _validate_field_value produces the correct nested error shape."""
        payload = current = {}
        for i in range(12):
            child = {}
            current[f"l{i}"] = child
            current = child
        current["leaf"] = "value"

        errors = {}
        mixin_instance._validate_field_value("my_dict", payload, None, errors)

        assert "my_dict" in errors
        inner = errors["my_dict"]
        assert isinstance(inner, dict)
        assert "my_dict" not in inner

    @patch(_VFT)
    def test_grandfathering_list_unchanged_items(self, mock_vft, mixin_instance):
        """Unchanged list items are grandfathered (skipped) via inherited DAB helpers."""
        errors = {}
        mixin_instance._validate_field_value("f", ["kept"], ["kept"], errors)
        mock_vft.assert_not_called()
        assert errors == {}

    @patch(_VFT)
    def test_grandfathering_dict_unchanged_values(self, mock_vft, mixin_instance):
        """Unchanged dict values are grandfathered (skipped) via inherited DAB helpers."""
        errors = {}
        mixin_instance._validate_field_value("f", {"k": "same"}, {"k": "same"}, errors)
        mock_vft.assert_not_called()
        assert errors == {}

    @patch(_VFT)
    def test_nested_dict_in_list_recurses(self, mock_vft, mixin_instance):
        """Nested dict inside list is validated recursively via DAB helpers."""
        errors = {}
        mixin_instance._validate_field_value("f", [{"key": "val"}], None, errors)
        mock_vft.assert_called_once_with("val")

    @patch(_VFT)
    def test_nested_list_in_dict_recurses(self, mock_vft, mixin_instance):
        """Nested list inside dict is validated recursively via DAB helpers."""
        errors = {}
        mixin_instance._validate_field_value("f", {"key": ["val"]}, None, errors)
        mock_vft.assert_called_once_with("val")


# ===================================================================
# 4. _run_text_validator integration (inherited from DAB)
# ===================================================================


class TestRunTextValidatorIntegration:
    """Inherited _run_text_validator: exception handling via DAB."""

    @patch(_VFT, side_effect=RuntimeError("boom"))
    @patch(_GS_DAB, return_value=True)
    def test_unexpected_exception_adds_incomplete_error(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._run_text_validator("field", "val", errors)
        assert "field" in errors
        assert errors["field"] == [_INCOMPLETE_VALIDATION_MSG]

    @patch(_VFT, side_effect=RuntimeError("boom"))
    @patch(_GS_DAB, return_value=False)
    def test_unexpected_exception_skipped_when_validation_disabled(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._run_text_validator("field", "val", errors)
        assert errors == {}


# ===================================================================
# 5. _log_validation_failure override: list vs string detail
# ===================================================================


class TestLogValidationFailureOverride:
    """_log_validation_failure override handles both list and string detail."""

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_list_detail_joined(self, mock_logger, mixin_instance):
        mixin_instance._log_validation_failure("field", ["err1", "err2"])
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "err1; err2" in call_args[0][3]

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_string_detail_used_directly(self, mock_logger, mixin_instance):
        mixin_instance._log_validation_failure("field", "single error")
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "single error" in call_args[0][3]

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_control_chars_in_detail_sanitized(self, mock_logger, mixin_instance):
        """Control characters in validation detail are escaped before logging."""
        mixin_instance._log_validation_failure("field", ["err\x00one", "err\x1ftwo"])
        mock_logger.warning.assert_called_once()
        reason = mock_logger.warning.call_args[0][3]
        assert "\x00" not in reason
        assert "\x1f" not in reason
        assert "err" in reason

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_resource_type_uses_preference_stub(self, mock_logger, mixin_instance):
        """Log message includes the Preference model stub resource type."""
        mixin_instance._log_validation_failure("field", "error")
        call_args = mock_logger.warning.call_args
        assert "aap_gateway_api.Preference" in call_args[0][2]


# ===================================================================
# 6. _clean_text_validate: gating and field filtering
# ===================================================================


class TestCleanTextValidateGating:
    """_clean_text_validate: disabled gate, excluded fields, unknown fields."""

    @patch(_GS_JEWEL, return_value=False)
    def test_returns_empty_when_disabled(self, _gs, mixin_instance):
        result = mixin_instance._clean_text_validate(
            {"test_field": "<script>"},
            {},
        )
        assert result == {}

    @patch(_VFT)
    @patch(_GS_JEWEL, return_value=True)
    def test_excluded_field_skipped(self, _gs, mock_vft, mixin_instance):
        result = mixin_instance._clean_text_validate(
            {"custom_login_info": "<b>html</b>"},
            {},
        )
        mock_vft.assert_not_called()
        assert result == {}

    @patch(_VFT)
    @patch(_GS_JEWEL, return_value=True)
    def test_unknown_field_skipped(self, _gs, mock_vft, mixin_instance):
        """A field name not in serializer fields is silently skipped."""
        result = mixin_instance._clean_text_validate(
            {"nonexistent_field": "value"},
            {},
        )
        mock_vft.assert_not_called()
        assert result == {}


# ===================================================================
# 7. _run_clean_text_on_pending_saves (integration via SettingSectionSerializer)
# ===================================================================


@pytest.mark.django_db
class TestRunCleanTextOnPendingSaves:
    """Covers _run_clean_text_on_pending_saves on SettingSectionSerializer."""

    def test_empty_dict_returns_empty(self):
        from aap_gateway_api.serializers.preferences import SettingSectionSerializer

        s = SettingSectionSerializer(category_slug="all")
        assert s._run_clean_text_on_pending_saves({}) == {}

    def test_none_returns_empty(self):
        from aap_gateway_api.serializers.preferences import SettingSectionSerializer

        s = SettingSectionSerializer(category_slug="all")
        assert s._run_clean_text_on_pending_saves(None) == {}

    def test_all_encrypted_returns_empty(self, register_preference, settings):
        """When every pending save is encrypted, nothing reaches clean-text."""
        settings.ENHANCED_INPUT_VALIDATION_ENABLED = True
        register_preference(
            section="cleantext_test",
            preference_name="enc_only",
            default="secret",
            preference_type="string",
            encrypted=True,
        )

        from aap_gateway_api.serializers.preferences import SettingSectionSerializer

        s = SettingSectionSerializer(category_slug="cleantext_test")
        result = s._run_clean_text_on_pending_saves(
            {
                "enc_only": {
                    "value": "<script>alert(1)</script>",
                    "section": "cleantext_test",
                    "persisted_value": "old_secret",
                },
            }
        )
        assert result == {}

    def test_non_encrypted_pref_validated(self, register_preference, settings):
        """A non-encrypted pref with a dangerous value produces an error."""
        settings.ENHANCED_INPUT_VALIDATION_ENABLED = True
        register_preference(
            section="cleantext_test",
            preference_name="plain_pref",
            default="safe",
            preference_type="string",
            encrypted=False,
        )

        from aap_gateway_api.serializers.preferences import SettingSectionSerializer

        s = SettingSectionSerializer(category_slug="cleantext_test")
        result = s._run_clean_text_on_pending_saves(
            {
                "plain_pref": {
                    "value": "<script>alert(1)</script>",
                    "section": "cleantext_test",
                    "persisted_value": "safe",
                },
            }
        )
        assert "plain_pref" in result
