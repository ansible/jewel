import pytest

from aap_gateway_api.utils import preferences
from aap_gateway_api.utils import ENCRYPTED_STRING


def test_register_exceptions():
    with pytest.raises(NameError) as e:
        preferences.register(preference_name=None)
    assert str(e.value) == "A preference must have a name"

    with pytest.raises(NotImplementedError) as e:
        preferences.register(preference_name="foo", preference_type="some_weird_type")
    assert (
        str(e.value)
        == "Preference type some_weird_type is not yet implemented in preferences utils"
    )


def test_get_preference_value_exceptions():
    with pytest.raises(ValueError) as e:
        preferences.get_preference_value("", "foo")
    assert str(e.value) == "You must pass get_preference_value a section and a name"

    with pytest.raises(ValueError) as e:
        preferences.get_preference_value("foo", "")
    assert str(e.value) == "You must pass get_preference_value a section and a name"


def test_encrypted_preference():
    preferences.register(
        section="general",
        preference_name="enc_test",
        encrypted=True,
        preference_type="string",
    )
    assert preferences.get_preference_value("general", "enc_test") == ENCRYPTED_STRING


def test_get_preference_sections():
    sections = preferences.get_preference_sections()
    assert "general" in sections
