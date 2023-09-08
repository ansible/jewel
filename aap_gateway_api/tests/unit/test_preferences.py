import pytest

from aap_gateway_api.utils import preferences


def test_register_exceptions():
    with pytest.raises(NameError) as e:
        preferences.register(preference_name=None)
    assert str(e.value) == "A preference must have a name"

    with pytest.raises(NotImplementedError) as e:
        preferences.register(preference_name="foo", preference_type="some_weird_type")
    assert str(e.value) == "Preference type some_weird_type is not yet implemented in preferences utils"
