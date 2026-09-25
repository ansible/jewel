"""Unit tests for PlainSerializerCleanTextMixin helpers and recursive paths.

These tests exercise the extracted helper methods and edge cases directly,
using mocks to control ``validate_free_text`` and ``get_setting`` without
needing the full API endpoint or database.

Coverage targets: static helpers, type dispatch, JSON recursion with
depth limits, grandfathering, error shape, unexpected-exception branches,
encrypted-field exclusion, and the validate-and-save clean-text path.
"""

from unittest.mock import patch

import pytest
from rest_framework import serializers

from aap_gateway_api.serializers.preferences import _INCOMPLETE_VALIDATION_MSG, PlainSerializerCleanTextMixin

# ---------------------------------------------------------------------------
# Minimal test serializer that exposes the mixin without Django models
# ---------------------------------------------------------------------------


class _TestMixinSerializer(PlainSerializerCleanTextMixin, serializers.Serializer):
    """Thin wrapper exposing the mixin for isolated testing."""

    test_field = serializers.CharField(required=False)
    test_list = serializers.ListField(required=False)
    test_json = serializers.JSONField(required=False)


@pytest.fixture
def mixin_instance():
    """Create a fresh mixin-backed serializer for each test."""
    return _TestMixinSerializer()


# ===================================================================
# 1. Static helper tests
# ===================================================================


class TestGetStoredListItem:
    """_get_stored_list_item: safe index lookup into stored list data."""

    @pytest.mark.parametrize(
        "stored_data, idx, expected",
        [
            (["a", "b", "c"], 0, "a"),
            (["a", "b", "c"], 2, "c"),
            (["a", "b", "c"], 3, None),
            (None, 0, None),
            ("not_a_list", 0, None),
            ({}, 0, None),
            ([], 0, None),
        ],
        ids=[
            "valid_first",
            "valid_last",
            "out_of_bounds",
            "none_stored",
            "string_stored",
            "dict_stored",
            "empty_list",
        ],
    )
    def test_returns_expected(self, stored_data, idx, expected):
        assert PlainSerializerCleanTextMixin._get_stored_list_item(stored_data, idx) == expected


class TestSanitizeDictKey:
    """_sanitize_dict_key: escapes C0/C1 control characters in keys."""

    def test_plain_string_unchanged(self):
        assert PlainSerializerCleanTextMixin._sanitize_dict_key("normal") == "normal"

    def test_control_chars_escaped(self):
        result = PlainSerializerCleanTextMixin._sanitize_dict_key("a\x00b\x1fc")
        assert "\x00" not in result
        assert "\x1f" not in result
        assert result.startswith("a")

    def test_non_string_returned_as_is(self):
        assert PlainSerializerCleanTextMixin._sanitize_dict_key(42) == 42
        assert PlainSerializerCleanTextMixin._sanitize_dict_key(None) is None


class TestGetStoredDictValue:
    """_get_stored_dict_value: safe key lookup into stored dict data."""

    @pytest.mark.parametrize(
        "stored_data, key, expected",
        [
            ({"a": 1}, "a", 1),
            ({"a": 1}, "missing", None),
            (None, "k", None),
            ([], "k", None),
            (42, "k", None),
        ],
        ids=[
            "key_present",
            "key_absent",
            "none_stored",
            "list_stored",
            "int_stored",
        ],
    )
    def test_returns_expected(self, stored_data, key, expected):
        assert PlainSerializerCleanTextMixin._get_stored_dict_value(stored_data, key) == expected


# ===================================================================
# 2. _validate_field_value type dispatch
# ===================================================================


class TestValidateFieldValue:
    """_validate_field_value: routes str/list/dict to the right validator."""

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_changed_string_runs_validation(self, _gs, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "new", "old", errors)
        mock_vft.assert_called_once_with("new")

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    def test_unchanged_string_skipped(self, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "same", "same", errors)
        mock_vft.assert_not_called()
        assert errors == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_list_value_dispatches(self, _gs, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", ["item"], None, errors)
        mock_vft.assert_called_once_with("item")

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_dict_value_dispatches(self, _gs, mock_vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", {"k": "v"}, None, errors)
        mock_vft.assert_called_once_with("v")

    def test_non_text_type_ignored(self, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", 42, None, errors)
        assert errors == {}
        mixin_instance._validate_field_value("f", True, None, errors)
        assert errors == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=serializers.ValidationError(["bad"]))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_string_failure_collects_error(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("f", "evil", "old", errors)
        assert "f" in errors

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=serializers.ValidationError(["bad"]))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_list_failure_collects_error_under_field_name(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("my_list", ["evil"], None, errors)
        assert "my_list" in errors

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=serializers.ValidationError(["bad"]))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_dict_failure_collects_error_under_field_name(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_field_value("my_dict", {"k": "evil"}, None, errors)
        assert "my_dict" in errors


# ===================================================================
# 3. _validate_json_list: recursion, depth limit, grandfathering
# ===================================================================


class TestValidateJsonList:
    """_validate_json_list: validates string leaves in lists."""

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_empty_list_returns_empty_dict(self, _gs, _vft, mixin_instance):
        assert mixin_instance._validate_json_list([], field_name="f") == {}

    def test_depth_limit_returns_error(self, mixin_instance):
        result = mixin_instance._validate_json_list(
            ["anything"],
            field_name="pref",
            depth=mixin_instance._MAX_JSON_DEPTH,
        )
        assert "pref" in result
        assert result["pref"] == [_INCOMPLETE_VALIDATION_MSG]

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_grandfathering_skips_unchanged_items(self, _gs, mock_vft, mixin_instance):
        result = mixin_instance._validate_json_list(
            ["kept"],
            field_name="f",
            stored_data=["kept"],
        )
        mock_vft.assert_not_called()
        assert result == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_changed_item_validated(self, _gs, mock_vft, mixin_instance):
        mixin_instance._validate_json_list(
            ["changed"],
            field_name="f",
            stored_data=["original"],
        )
        mock_vft.assert_called_once_with("changed")

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_dict_inside_list_recurses(self, _gs, mock_vft, mixin_instance):
        mixin_instance._validate_json_list(
            [{"nested_key": "val"}],
            field_name="f",
        )
        mock_vft.assert_called_once_with("val")

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_list_inside_list_recurses(self, _gs, mock_vft, mixin_instance):
        mixin_instance._validate_json_list(
            [["inner"]],
            field_name="f",
        )
        mock_vft.assert_called_once_with("inner")

    def test_deeply_nested_list_hits_depth_limit(self, mixin_instance):
        """Nested lists beyond _MAX_JSON_DEPTH produce an error."""
        data = current = []
        for _ in range(12):
            child = []
            current.append(child)
            current = child
        current.append("leaf")

        result = mixin_instance._validate_json_list(data, field_name="deep")
        assert result  # non-empty means depth-limit error was raised


# ===================================================================
# 4. _validate_json_dict: recursion, depth limit, grandfathering
# ===================================================================


class TestValidateJsonDict:
    """_validate_json_dict: validates string leaves in dicts."""

    def test_depth_limit_error_key_uses_field_name(self, mixin_instance):
        """Without key_prefix, error key is the field_name."""
        result = mixin_instance._validate_json_dict(
            {"k": "v"},
            field_name="pref",
            depth=mixin_instance._MAX_JSON_DEPTH,
        )
        assert "pref" in result
        assert result["pref"] == [_INCOMPLETE_VALIDATION_MSG]

    def test_depth_limit_error_key_uses_key_prefix(self, mixin_instance):
        """With key_prefix, error key uses the nesting path."""
        result = mixin_instance._validate_json_dict(
            {"k": "v"},
            field_name="pref",
            key_prefix="[0].inner.",
            depth=mixin_instance._MAX_JSON_DEPTH,
        )
        assert "[0].inner" in result

    def test_depth_limit_mutates_passed_errors_dict(self, mixin_instance):
        """When errors dict is passed in, depth-limit error is merged into it."""
        errors = {"existing": "error"}
        mixin_instance._validate_json_dict(
            {"k": "v"},
            field_name="pref",
            depth=mixin_instance._MAX_JSON_DEPTH,
            errors=errors,
        )
        assert "pref" in errors
        assert "existing" in errors  # original errors preserved

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_grandfathering_skips_unchanged(self, _gs, mock_vft, mixin_instance):
        result = mixin_instance._validate_json_dict(
            {"key": "same_val"},
            field_name="f",
            stored_data={"key": "same_val"},
        )
        mock_vft.assert_not_called()
        assert result == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_list_inside_dict_recurses(self, _gs, mock_vft, mixin_instance):
        mixin_instance._validate_json_dict(
            {"key": ["val"]},
            field_name="f",
        )
        mock_vft.assert_called_once_with("val")

    def test_deeply_nested_dict_hits_depth_limit(self, mixin_instance):
        payload = current = {}
        for i in range(12):
            child = {}
            current[f"l{i}"] = child
            current = child
        current["leaf"] = "value"

        result = mixin_instance._validate_json_dict(payload, field_name="deep")
        assert result  # non-empty means depth-limit error was raised

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_empty_dict_returns_empty(self, _gs, _vft, mixin_instance):
        result = mixin_instance._validate_json_dict({}, field_name="f")
        assert result == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_non_string_values_skipped(self, _gs, mock_vft, mixin_instance):
        """Integer and boolean values inside dicts should not be validated."""
        result = mixin_instance._validate_json_dict(
            {"num": 42, "flag": True},
            field_name="f",
        )
        mock_vft.assert_not_called()
        assert result == {}


# ===================================================================
# 5. _run_clean_text_validator: unexpected-exception branch
# ===================================================================


class TestRunCleanTextValidatorExceptionBranch:
    """Covers the generic Exception handler in _run_clean_text_validator."""

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=RuntimeError("boom"))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_unexpected_exception_adds_incomplete_error(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._run_clean_text_validator("field", "val", errors)
        assert "field" in errors
        assert errors["field"] == [_INCOMPLETE_VALIDATION_MSG]

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=RuntimeError("boom"))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=False)
    def test_unexpected_exception_skipped_when_validation_disabled(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._run_clean_text_validator("field", "val", errors)
        assert errors == {}


# ===================================================================
# 6. _validate_json_string: unexpected-exception branch
# ===================================================================


class TestValidateJsonStringExceptionBranch:
    """Covers the generic Exception handler in _validate_json_string."""

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=RuntimeError("boom"))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_unexpected_exception_adds_incomplete_error(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_json_string("val", "key", errors, "field")
        assert "key" in errors
        assert errors["key"] == [_INCOMPLETE_VALIDATION_MSG]

    @patch("aap_gateway_api.serializers.preferences.validate_free_text", side_effect=RuntimeError("boom"))
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=False)
    def test_unexpected_exception_skipped_when_validation_disabled(self, _gs, _vft, mixin_instance):
        errors = {}
        mixin_instance._validate_json_string("val", "key", errors, "field")
        assert errors == {}


# ===================================================================
# 7. _log_clean_text_failure: list vs string detail
# ===================================================================


class TestLogCleanTextFailure:
    """_log_clean_text_failure handles both list and string detail."""

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_list_detail_joined(self, mock_logger, mixin_instance):
        mixin_instance._log_clean_text_failure("field", ["err1", "err2"])
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "err1; err2" in call_args[0][3]

    @patch("aap_gateway_api.serializers.preferences.logger")
    def test_string_detail_used_directly(self, mock_logger, mixin_instance):
        mixin_instance._log_clean_text_failure("field", "single error")
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "single error" in call_args[0][3]


# ===================================================================
# 8. _clean_text_validate: gating and field filtering
# ===================================================================


class TestCleanTextValidateGating:
    """_clean_text_validate: disabled gate, excluded fields, unknown fields."""

    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=False)
    def test_returns_empty_when_disabled(self, _gs, mixin_instance):
        result = mixin_instance._clean_text_validate(
            {"test_field": "<script>"},
            {},
        )
        assert result == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_excluded_field_skipped(self, _gs, mock_vft, mixin_instance):
        result = mixin_instance._clean_text_validate(
            {"custom_login_info": "<b>html</b>"},
            {},
        )
        mock_vft.assert_not_called()
        assert result == {}

    @patch("aap_gateway_api.serializers.preferences.validate_free_text")
    @patch("aap_gateway_api.serializers.preferences.get_setting", return_value=True)
    def test_unknown_field_skipped(self, _gs, mock_vft, mixin_instance):
        """A field name not in serializer fields is silently skipped."""
        result = mixin_instance._clean_text_validate(
            {"nonexistent_field": "value"},
            {},
        )
        mock_vft.assert_not_called()
        assert result == {}


# ===================================================================
# 9. _run_clean_text_on_pending_saves (integration via SettingSectionSerializer)
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
