import pytest
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url
from django.core.cache import cache
from django.test import override_settings

from aap_gateway_api.models import Preference
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.serializers.preferences import SettingSectionSerializer


@override_settings(AOC_UNCHANGEABLE_PREFERENCES=['gateway_token_name'])
@pytest.mark.parametrize(
    "is_cloud_install",
    [
        (True),
        (False),
    ],
)
def test_process_fields_aoc_read_only_options_page(is_cloud_install, admin_api_client):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=is_cloud_install):
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert 'actions' in response.data
        assert 'PUT' in response.data['actions']
        assert 'gateway_token_name' in response.data['actions']['PUT']
        assert 'read_only' in response.data['actions']['PUT']['gateway_token_name']
        assert response.data['actions']['PUT']['gateway_token_name']['read_only'] is is_cloud_install


@override_settings(AOC_UNCHANGEABLE_PREFERENCES=['gateway_token_name'])
@pytest.mark.parametrize(
    "is_cloud_install, expected_response_code",
    [
        (True, 400),
        (False, 200),
    ],
)
def test_process_fields_aoc_change_read_only_setting(is_cloud_install, expected_response_code, admin_api_client):
    preference_name = "gateway_token_name"
    try:
        with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=is_cloud_install):
            url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
            response = admin_api_client.put(url, {preference_name: 'testing'})
            assert response.status_code == expected_response_code
            if is_cloud_install:
                assert 'gateway_token_name' in response.data
                assert response.data[preference_name] == f"{preference_name} is read-only by AoC environment"
    finally:
        # The DB change is rolled back by the test's savepoint, but the preference
        # cache (fakeredis) is not transactional.  Clear the stale cache entry so
        # subsequent tests read the real value from DB.
        cache_key = gateway_preference_registry.manager().get_cache_key("proxy", preference_name)
        cache.delete(cache_key)


def test_secret_field_retains_original_value_when_passed_encrypted_marker(admin_api_client, register_preference):
    """
    Ensure that the secret field value is preserved when '$encrypted$' is passed during update
    """
    register_preference(section='general', preference_name='preference_1', default='one', encrypted=True)
    register_preference(section='general', preference_name='preference_2', default='two', encrypted=True)

    preference_1 = Preference.objects.get(section="general", name="preference_1")
    preference_2 = Preference.objects.get(section="general", name="preference_2")
    assert preference_1.value == 'one' and preference_2.value == 'two'

    url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})

    # check that the value is encrypted on the API
    get_res = admin_api_client.get(url)
    assert get_res.data["preference_1"] == ENCRYPTED_STRING and get_res.data["preference_2"] == ENCRYPTED_STRING

    # now, update preference_1 with a normal value
    # and preference_2 with the encrypted marker
    put_res = admin_api_client.put(url, {'preference_1': 'i_am_updated', 'preference_2': ENCRYPTED_STRING})
    assert put_res.status_code == 200

    # get the preference objects from DB again
    preference_1 = Preference.objects.get(section="general", name="preference_1")
    preference_2 = Preference.objects.get(section="general", name="preference_2")

    # ensure that preference_1 is updated with the new value,
    # and preference_2 preserves its original value
    assert preference_1.value == 'i_am_updated'
    assert preference_2.value == 'two'


@pytest.mark.parametrize(
    "preference_type, bad_return_value, expected_error",
    [
        ("int", "not_an_int", "Must be an integer"),
        ("string", 999, "Must be a string"),
    ],
)
def test_serialize_validate_rejects_wrong_type_from_to_python(register_preference, preference_type, bad_return_value, expected_error):
    """_serialize_and_validate_preference_value raises when to_python returns a wrong type."""
    from unittest.mock import patch

    from aap_gateway_api.preferences import gateway_preference_registry

    default = 0 if preference_type == "int" else "default"
    register_preference(
        section="general",
        preference_name="type_check_pref",
        default=default,
        encrypted=False,
        preference_type=preference_type,
    )

    serializer = SettingSectionSerializer(category_slug="general")
    registered_pref = gateway_preference_registry.get("type_check_pref", "general")

    with patch.object(registered_pref.serializer, 'to_python', return_value=bad_return_value):
        with patch.object(registered_pref, 'validate'):
            is_valid, parsed_value, err_msg = serializer._serialize_and_validate_preference_value(registered_pref, "bogus")

    assert not is_valid
    assert expected_error in err_msg


def test_json_strings_are_not_double_deserialized(admin_api_client, register_preference):
    """
    Ensure that JSON preferences that are strings have their html form values rendered without being wrapped with json.dumps
    """
    register_preference(section='testing', preference_name='preference_1', default='one', encrypted=False, preference_type="json")
    register_preference(section='testing', preference_name='preference_2', default='two', encrypted=True, preference_type="json")

    preferences = SettingSectionSerializer(category_slug="testing")
    # Get the actual values of these preferences, or '$encrypted$' if encrypted
    preference_1 = preferences.data["preference_1"]
    preference_2 = preferences.data["preference_2"]

    # Compare the actual values to their DRF HTML form fields, which should not fail for these particular preferences
    assert preference_1 == preferences["preference_1"].as_form_field().value
    assert preference_2 == preferences["preference_2"].as_form_field().value
