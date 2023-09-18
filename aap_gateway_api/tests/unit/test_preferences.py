from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from dynamic_preferences.serializers import SerializationError

from aap_gateway_api.models import Preference
from aap_gateway_api.utils import ENCRYPTED_STRING, preferences


def test_register_exceptions():
    with pytest.raises(NameError) as e:
        preferences.register(preference_name=None)
    assert str(e.value) == "A preference must have a name"

    with pytest.raises(NotImplementedError) as e:
        preferences.register(preference_name="foo", preference_type="some_weird_type")
    assert str(e.value) == "Preference type some_weird_type is not yet implemented in preferences utils"


def test_get_preference_value_exceptions():
    with pytest.raises(ValueError) as e:
        preferences.get_preference_value("", "foo")
    assert str(e.value) == "You must pass get_preference_value a section and a name"

    with pytest.raises(ValueError) as e:
        preferences.get_preference_value("foo", "")
    assert str(e.value) == "You must pass get_preference_value a section and a name"


def test_preference_with_invalid_url(set_preference):
    with pytest.raises(ValidationError) as e:
        set_preference("proxy", "gateway_proxy_url", "monkey://banana")
    assert str(e.value.message) == "monkey://banana is not a valid URL"


def test_get_preference_sections():
    sections = preferences.get_preference_sections()
    assert "general" in sections


def test_meta_register_preference_fixture(register_preference):
    register_preference(
        section="general",
        preference_name="test_preference",
        default="test",
        required=False,
        encrypted=False,
        preference_type="string",
        help_text="This is a test preference",
    )
    assert preferences.get_preference_value("general", "test_preference") == "test"


def test_encrypted_preference(register_preference):
    register_preference(
        section="general",
        preference_name="enc_test",
        default="hey",
        encrypted=True,
        preference_type="string",
    )

    # Ensure we can encrypt and decrypt
    assert preferences.get_preference_value("general", "enc_test") == ENCRYPTED_STRING
    preference = Preference.objects.get(section="general", name="enc_test")
    assert preference.value == "hey"

    # Ensure we can update the value and still decrypt
    preference.value = "hello test"
    preference.save()

    assert preferences.get_preference_value("general", "enc_test") == ENCRYPTED_STRING
    preference = Preference.objects.get(section="general", name="enc_test")
    assert preference.value == "hello test"


@pytest.mark.parametrize(
    "preference_type, default, value, err_substring",
    [
        # NOTE: If you add cases to this matrix, add them in functional/test_settings.py, too.
        ("string", "foo", 1234, "Cannot serialize, value 1234 is not a string"),  # In the API this gets coerced and works
        ("string", "foo", True, "Cannot serialize, value True is not a string"),  # In the API this gets coerced and works
        ("bool", False, "true", "true is not a boolean"),
        ("bool", False, 1, "1 is not a boolean"),
        ("bool", False, "true", "true is not a boolean"),
        ("bool", False, 1, "1 is not a boolean"),
        ("bool", False, "1", "1 is not a boolean"),
        ("bool", False, "false", "false is not a boolean"),
        ("bool", False, 0, "0 is not a boolean"),
        ("bool", False, "0", "0 is not a boolean"),
        ("int", 0, "not an int", "IntSerializer can only serialize int values"),
        ("int", 0, False, None),  # In the API this does *not* work. But it does here.
        ("url", "https://example.com", 1337, "1337 is not a valid URL"),
    ],
)
def test_preference_update_with_bad_type(register_preference, preference_type, default, value, err_substring):
    """
    Test setting a preference with a bad type.
    """
    register_preference(
        section="general",
        preference_name="bad_type",
        default=default,
        encrypted=False,
        preference_type=preference_type,
    )

    if err_substring is not None:
        with pytest.raises((ValidationError, SerializationError)) as e:
            preferences.update_preference_value("general", "bad_type", value)

        if isinstance(e.value, ValidationError):
            assert err_substring in e.value.message
        else:
            assert err_substring in str(e.value)
    else:
        # Just make sure this doesn't raise an exception
        preferences.update_preference_value("general", "bad_type", value)


def test_preference_on_update(register_preference):
    on_update_callback = MagicMock()

    register_preference(
        section="general",
        preference_name="on_update_test",
        default="hey",
        encrypted=False,
        preference_type="string",
        on_update=on_update_callback,
    )

    assert on_update_callback.call_count == 0

    # Ensure the callback is called even if the value is the same
    preferences.update_preference_value("general", "on_update_test", "hey")
    assert on_update_callback.call_count == 1

    on_update_callback.reset_mock()

    # Change the value and ensure the callback is called
    preferences.update_preference_value("general", "on_update_test", "hello test")
    assert on_update_callback.call_count == 1

    # The callback gets 2 parameters, the old value, and the new value
    assert on_update_callback.call_args[0][0] == "hey"
    assert on_update_callback.call_args[0][1] == "hello test"
