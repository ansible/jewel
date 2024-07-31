from unittest.mock import MagicMock, patch

import pytest
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.settings import SettingNotSetException
from django.core.exceptions import ValidationError
from dynamic_preferences.managers import PreferencesManager
from dynamic_preferences.serializers import SerializationError

from aap_gateway_api.models import Preference
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.preferences.registry import PreferenceRegistry
from aap_gateway_api.utils import preferences


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
    assert "proxy" in sections


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


def test_get_setting_not_set():
    with pytest.raises(SettingNotSetException):
        preferences.get_setting('junk_preference_name')


def test_get_setting_set(register_preference):
    register_preference(
        section="general",
        preference_name="test_preference",
        default="hey",
        encrypted=False,
        preference_type="string",
    )
    value = preferences.get_setting('test_preference')
    assert value == "hey"


def test_get_setting_too_many(register_preference):
    register_preference(
        section="general",
        preference_name="test_preference",
        default="hey",
        encrypted=False,
        preference_type="string",
    )
    register_preference(
        section="generic",
        preference_name="test_preference",
        default="hey there",
        encrypted=False,
        preference_type="string",
    )
    with pytest.raises(preferences.TooManyPreferencesException) as e:
        preferences.get_setting('test_preference')
    assert 'unable to get a setting by name' in str(e.value)


class CustomManager(PreferencesManager):
    def __init__(self, value):
        self.value = value

    def get(self, key, no_cache=False):
        from ansible_base.lib.utils.encryption import ansible_encryption

        encrypted_value = ansible_encryption.encrypt_string(self.value)
        return encrypted_value


def test_get_preference_value_gets_encrypted_value(register_preference):
    expected_value = 'hello'
    register_preference(
        section="general",
        preference_name="encrypted_test_value",
        default="Wrong Value",
        encrypted=True,
        preference_type="string",
    )

    with patch('aap_gateway_api.preferences.registry.gateway_preference_registry.manager', return_value=CustomManager(expected_value)):
        assert preferences.get_preference_value('general', 'encrypted_test_value', encrypted=False) == expected_value


def test_encrypted_manager(register_preference):
    value = 'hey'
    preference_name = 'enc_test'
    section = 'general'
    register_preference(
        section=section,
        preference_name=preference_name,
        default=value,
        encrypted=True,
        preference_type="string",
    )

    assert preferences.get_preference_value(section, preference_name) == ENCRYPTED_STRING

    encrypted_preference = preferences.gateway_preference_manager.get_db_pref(section, preference_name)

    with patch('django.core.cache.backends.redis.RedisCacheClient.set_many') as patched_cache:
        registry = PreferenceRegistry()
        manager = registry.manager()
        manager.to_cache(encrypted_preference)

        patched_cache.assert_called_once()
        settings_values = [*patched_cache.call_args_list[0][0][0].values()]
        assert len(settings_values) == 1
        assert value not in settings_values
        assert settings_values[0].startswith(ENCRYPTED_STRING)


@pytest.mark.parametrize("is_encrypted", [True, False])
def test_get_default_value_by_preference(register_preference, is_encrypted):

    register_preference(section='general', preference_name='test_get_default', default='iam_default', preference_type="string", encrypted=is_encrypted)

    preference = gateway_preference_registry.get('test_get_default', 'general')
    assert preferences.get_default_value_by_preference(preference, is_encrypted) == ENCRYPTED_STRING if is_encrypted else 'iam_default'
