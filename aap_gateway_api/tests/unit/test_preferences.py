import pytest
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
    with pytest.raises(SerializationError) as e:
        set_preference("proxy", "gateway_proxy_url", "monkey://banana")
    assert str(e.value) == "monkey://banana is not a valid URL"


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
