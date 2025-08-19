import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from aap_gateway_api.utils.preferences import get_setting


@pytest.mark.parametrize(
    "min_value,max_value",
    [
        (None, None),
        (7, None),
        (None, 7),
        (2, 87654321),
    ],
)
def test_min_max_value_of_int_range_type(min_value, max_value, register_preference, set_preference):
    from aap_gateway_api.preferences.types import IntRangePreference

    kwargs = {}
    if min_value:
        kwargs['min_value'] = min_value
        fail_low_value = min_value - 1
        pass_low_value = min_value
    else:
        fail_low_value = IntRangePreference.DEFAULT_MIN_VALUE - 1
        pass_low_value = IntRangePreference.DEFAULT_MIN_VALUE
    if max_value:
        kwargs['max_value'] = max_value
        fail_high_value = max_value + 1
        pass_high_value = max_value
    else:
        fail_high_value = IntRangePreference.DEFAULT_MAX_VALUE + 1
        pass_high_value = IntRangePreference.DEFAULT_MAX_VALUE

    register_preference(
        section="general",
        preference_name="test_preference",
        default=7,
        required=False,
        encrypted=False,
        preference_type="int_range",
        help_text="This is a test preference",
        **kwargs,
    )

    with pytest.raises(ValidationError):
        set_preference("general", "test_preference", fail_low_value)
    set_preference("general", "test_preference", pass_low_value)
    set_preference("general", "test_preference", pass_high_value)
    with pytest.raises(ValidationError):
        set_preference("general", "test_preference", fail_high_value)


@pytest.mark.parametrize(
    "csrf_setting,csrf_preference_value,exception",
    [
        ([], ["https://localhost"], None),
        ([], ["localhost"], "The origin must start with either http:// or https://\\. Got: localhost"),
        ([], ["https://localhost/path"], "The origin must include only the scheme and hostname \\(no path\\)\\. Got: https://localhost/path"),
        ([], ["https://"], "The hostname should not be empty\\. Got: https://"),
        ([], "https://localhost", "Must be a list of valid origins such as"),
        ([], ["*"], None),
        ([], ["https://*.example.com"], None),
        ([], ["https://*.example.com", "https://localhost"], None),
        (["https://localhost"], ["https://*.example.com", "https://localhost"], None),
        ([], 1, "Must be a list of valid origins such as"),
    ],
)
def test_csrf_trusted_origins_type(register_preference, set_preference, csrf_setting, csrf_preference_value, exception):
    with override_settings(CSRF_TRUSTED_ORIGINS=csrf_setting):
        register_preference(
            section="general",
            preference_name="test_preference",
            default=[],
            required=False,
            encrypted=False,
            preference_type="CSRF_list",
            help_text="This is a test preference",
        )
        if exception:
            with pytest.raises(ValidationError, match=exception):
                set_preference("general", "test_preference", csrf_preference_value)
        else:
            set_preference("general", "test_preference", csrf_preference_value)


def test_csrf_trusted_origins_changing_in_django_conf(register_preference, set_preference):
    register_preference(
        section="general",
        preference_name="test_preference",
        default=[],
        required=False,
        encrypted=False,
        preference_type="CSRF_list",
        help_text="This is a test preference",
    )

    with override_settings(CSRF_TRUSTED_ORIGINS=["*"]):
        assert get_setting('test_preference') == ["*"], "Trusted origin should have only been *"

        set_preference('general', 'test_preference', ["https://example.com"])
        assert get_setting('test_preference') == ["*", "https://example.com"]

    with override_settings(CSRF_TRUSTED_ORIGINS=["https://localhost"]):
        assert get_setting('test_preference') == ["https://localhost", "https://example.com"], "Trusted origin did not update properly"


def test_csrf_invalid_value_in_settings(register_preference, expected_log):
    with override_settings(CSRF_TRUSTED_ORIGINS=[">>>"]):
        with expected_log(
            'aap_gateway_api.preferences.serializers.logger',
            'error',
            "CSRF_TRUSTED_ORIGINS has an invalid value",
        ):
            register_preference(
                section="general",
                preference_name="test_preference",
                default=[],
                required=False,
                encrypted=False,
                preference_type="CSRF_list",
                help_text="This is a test preference",
            )


@pytest.mark.parametrize(
    "value, expected_error",
    [
        ("https://example.com", None),
        ("/path/to/file", None),
        ("not_a_url", "not_a_url is not a valid URL or absolute path"),
        ("not/an/absolute/path", "not/an/absolute/path is not a valid URL or absolute path"),
        ("http://example.com", None),
        ("mailto:test@example.com", "mailto:test@example.com is not a valid URL or absolute path"),
    ],
)
def test_absolute_path_or_url_preference(register_preference, set_preference, value, expected_error):
    register_preference(
        section="general",
        preference_name="test_preference",
        default="",
        required=False,
        encrypted=False,
        preference_type="absolute_path_or_url",
    )
    if expected_error:
        with pytest.raises(ValidationError) as e:
            set_preference("general", "test_preference", value)
        assert expected_error in str(e.value)
    else:
        set_preference("general", "test_preference", value)
