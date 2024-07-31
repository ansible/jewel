import pytest
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import Preference
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.utils.preferences import update_preference_value
from aap_gateway_api.views.api.v1.preference import SettingSectionViewSet


def test_get_all_settings(admin_api_client):
    """
    ensure we can access endpoint /api/gateway/v1/settings/all/
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "all"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert "gateway_token_name" in response.data


def test_get_all_setting_sections_and_urls(admin_api_client):
    """
    ensure that we can see url for each and all setting sections
    """
    viewset = SettingSectionViewSet()
    setting_sections = viewset.get_queryset()
    actual_data = [{'url': section.url, 'name': section.name} for section in setting_sections]

    url = get_relative_url("setting-list")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert actual_data == response.data['results']


def test_get_proxy_settings(admin_api_client):
    """
    ensure that we can see settings for proxy section
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "proxy"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert "gateway_token_name" in response.data


def test_get_all_settings_unauthenticated(unauthenticated_api_client):
    """
    ensure that unauthenticated user cannot see settings section
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "all"})
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


def test_set_setting(admin_api_client):
    """
    test if admin can successfully set a setting
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "all"})

    response = admin_api_client.get(url)
    original_value = response.data["gateway_token_name"]

    response = admin_api_client.put(url, data={"gateway_token_name": "X-FOO-BAR"})
    assert response.status_code == 200
    assert response.data["gateway_token_name"] == "X-FOO-BAR"

    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["gateway_token_name"] == "X-FOO-BAR"

    # Set it back to the original value
    response = admin_api_client.put(url, data={"gateway_token_name": original_value})
    assert response.status_code == 200
    assert response.data["gateway_token_name"] == original_value


def test_set_setting_unauthenticated(unauthenticated_api_client):
    """
    ensure that unauthenticated user cannot set settings
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "all"})
    response = unauthenticated_api_client.put(url, data={"gateway_token_name": "X-FOO-BAR-UNAUTH"})
    assert response.status_code == 401
    assert Preference.objects.filter(name="gateway_token_name").first().value != "X-FOO-BAR-UNAUTH"


def test_set_setting_invalid(admin_api_client):
    """
    ensure that user cannot set invalid setting by passing an arbitrary setting name
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "all"})
    response = admin_api_client.put(url, data={"nonexistent_setting": "X-FOO-BAR"})
    assert response.status_code == 400
    assert Preference.objects.filter(name="nonexistent_setting").count() == 0


@pytest.mark.parametrize(
    "preference_type, default, value, err_substring, new_value",
    [
        # NOTE: If you add cases to this matrix, add them to in unit/test_preferences.py, too.
        ("string", "foo", 1234, None, "1234"),
        ("string", "foo", True, None, "True"),
        ("bool", False, "true", None, True),
        ("bool", False, 1, None, True),
        ("bool", False, "1", None, True),
        ("bool", False, "false", None, False),
        ("bool", False, 0, None, False),
        ("bool", False, "0", None, False),
        ("int", 0, "not an int", "Value not an int cannot be converted to int", 0),
        ("int", 0, False, "Value False cannot be converted to int", 0),
        ("url", "https://example.com", 1337, "1337 is not a valid URL", "https://example.com"),
    ],
)
def test_set_setting_bad_type(admin_api_client, register_preference, preference_type, default, value, err_substring, new_value):
    """
    Test setting a preference via the API with a value of the wrong type.
    """
    register_preference(
        section="general",
        preference_name="bad_type",
        default=default,
        encrypted=False,
        preference_type=preference_type,
    )

    url = get_relative_url("setting-section-list", kwargs={"category_slug": "general"})
    response = admin_api_client.put(url, data={"bad_type": value})

    assert response.status_code == 200 if err_substring is None else 400

    if err_substring is not None:
        assert str(response.data["bad_type"]) == err_substring

    assert Preference.objects.filter(name="bad_type").first().value == new_value


@pytest.mark.parametrize(
    "preference",
    [
        ("proxy", "jwt_public_key"),
    ],
)
def test_set_readonly_setting(admin_api_client, preference):
    """
    ensure that user cannot set read-only setting
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": preference[0]})
    response = admin_api_client.put(url, data={preference[1]: "This should not work"})
    assert response.status_code == 400
    assert str(response.data[preference[1]]) == f"Cannot change read-only setting {preference[1]}"
    assert Preference.objects.filter(name=preference[1]).first().value != "This should not work"


def test_on_update_changes_reflected_in_put(admin_api_client, register_preference):
    """
    When a preference is updated, its on_update callback might change other preferences
    in the same section. Ensure that those changes are reflected in the response from
    the PUT request.
    """

    register_preference(
        section="general",
        preference_name="soda",
        default="root beer",
        on_update=lambda preference, old, new: update_preference_value("general", "soda_but_uppercase", new.upper()),
    )

    register_preference(
        section="general",
        default="root beer",
        preference_name="soda_but_uppercase",
    )

    url = get_relative_url("setting-section-list", kwargs={"category_slug": "general"})
    response = admin_api_client.put(url, data={"soda": "orange"})
    assert response.status_code == 200
    assert response.data["soda"] == "orange"
    assert response.data["soda_but_uppercase"] == "ORANGE"


def test_options_include_default_field(admin_api_client, register_preference):
    """
    ensure that all settings expose a default field in the API, except for encrypted settings.
    """
    register_preference(section='general', preference_name='my_secret', default='i_love_ansible', encrypted=True)
    register_preference(section='general', preference_name='another_secret', default='i_love_cats', encrypted=True)
    register_preference(section='general', preference_name='my_hobby', default='swimming', encrypted=False)

    url = get_relative_url("setting-section-list", kwargs={"category_slug": 'general'})
    response = admin_api_client.options(url)
    assert response.status_code == 200

    actions = response.data.get('actions', {})
    for method, preferences in actions.items():
        if method in ['PUT', 'POST']:
            for preference, value in preferences.items():
                is_encrypted = gateway_preference_registry.get(preference, 'general').encrypted
                has_default = 'default' in value
                assert has_default != is_encrypted, f"'default' should {'not ' if is_encrypted else ''}be present in preference '{preference}'."


# Note: DELETE request to /api/gateway/v1/settings/(?P<category_slug>[a-z0-9_]+)/
# means that the user wants to revert all settings tied to that endpoint back to their default values
@pytest.mark.django_db
@pytest.mark.parametrize(
    "client_fixture, category_slug, expected_status_code",
    [
        ("admin_api_client", "all", 200),
        ("platform_auditor_api_client", "proxy", 403),
        ("user_api_client", "all", 403),
        ("unauthenticated_api_client", "proxy", 401),
    ],
)
def test_delete_settings_with_different_permissions(request, client_fixture, category_slug, expected_status_code):
    """
    ensure that DELETE setting request are handled correctly with different permission types
    """
    url = get_relative_url("setting-section-list", kwargs={"category_slug": category_slug})
    client = request.getfixturevalue(client_fixture)
    response = client.delete(url)
    assert response.status_code == expected_status_code


@pytest.mark.django_db
@pytest.mark.parametrize(
    "setup_test_preferences",
    [
        ["fruit", "animal"],
    ],
    indirect=True,
)
def test_revert_all_changed_to_default_setting(admin_api_client, setup_test_preferences):
    """
    test reverting all preferences in the current category to their default values behaves correctly
    """
    fruit, animal = [preference.name for preference in setup_test_preferences]
    url = get_relative_url("setting-section-list", kwargs={"category_slug": "general"})

    # check current value of preference 'fruit' and 'animal'
    response = admin_api_client.get(url)
    assert response.data[fruit] == f"{fruit}_updated"
    assert response.data[animal] == f"{animal}_updated"

    # revert all changed preferences to their default
    delete_response = admin_api_client.delete(url)
    assert delete_response.status_code == 200

    # now try GET again to see if settings is back to default
    get_response = admin_api_client.get(url)
    assert get_response.status_code == 200
    assert get_response.data[fruit] == f"{fruit}_default"
    assert get_response.data[animal] == f"{animal}_default"


# test GET/ DELETE requests to api/gateway/v1/settings/(?P<category_slug>[a-z0-9_]+)/(?P<preference_name>[a-zA-Z0-9_]+)/$
# note: this endpoint requires category to be specific (not 'all'). If a category is not specified, return a 404
@pytest.mark.django_db
@pytest.mark.parametrize(
    "client_fixture, category_slug, preference_name, expected_status_code",
    [
        ("unauthenticated_api_client", "proxy", "gateway_token_name", 401),
        ("user_api_client", "proxy", "gateway_token_name", 403),
        ("platform_auditor_api_client", "proxy", "gateway_token_name", 200),
        ("admin_api_client", "proxy", "gateway_token_name", 200),
        ("admin_api_client", "all", "gateway_token_name", 404),
    ],
)
def test_get_a_setting_with_different_permissions(request, client_fixture, category_slug, preference_name, expected_status_code):
    """
    ensure that GET setting request under the specified section are handled correctly with different permission types
    """
    url = get_relative_url("setting-detail", kwargs={"category_slug": category_slug, "preference_name": preference_name})
    client = request.getfixturevalue(client_fixture)
    response = client.get(url)
    assert response.status_code == expected_status_code
    if category_slug == "all":
        assert f"Please include the appropriate category in the URL to which the preference '{preference_name}' belongs." in response.data["detail"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "setup_test_preferences",
    [
        ["fruit", "animal"],
    ],
    indirect=True,
)
def test_revert_a_setting_to_default(admin_api_client, setup_test_preferences):
    """
    ensure that reverting a single setting within the specified section doesn't affect other settings
    """

    fruit_pref, animal_pref = [preference.name for preference in setup_test_preferences]

    fruit_url = get_relative_url("setting-detail", kwargs={"category_slug": "general", "preference_name": fruit_pref})
    animal_url = get_relative_url("setting-detail", kwargs={"category_slug": "general", "preference_name": animal_pref})

    # check that values of preferences are updated
    get_fruit = admin_api_client.get(fruit_url)
    assert get_fruit.data["value"] == "fruit_updated"
    get_animal = admin_api_client.get(animal_url)
    assert get_animal.data["value"] == "animal_updated"

    # revert the fruit preference to default
    delete_fruit = admin_api_client.delete(fruit_url)
    assert delete_fruit.status_code == 200
    assert delete_fruit.data["detail"] == "Preference 'fruit' in category 'general' reverted to default value."

    # get the preference value again to ensure it is reverted to default
    get_fruit = admin_api_client.get(fruit_url)
    assert get_fruit.status_code == 200
    assert get_fruit.data["value"] == "fruit_default"

    # ensure that there is nothing changed to preference 2 value
    get_animal = admin_api_client.get(animal_url)
    assert get_animal.status_code == 200
    assert get_animal.data["value"] == "animal_updated"


def test_get_and_revert_single_setting_encrypted(admin_api_client, register_preference):
    """
    ensure that an encrypted preference is masked with ENCRYPTED_STRING
    """
    register_preference(section='general', preference_name='my_secret', default='i_love_ansible', encrypted=True)
    url = get_relative_url("setting-detail", kwargs={"category_slug": 'general', "preference_name": 'my_secret'})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["value"] == ENCRYPTED_STRING


def test_revert_with_encrypted_setting(admin_api_client, register_preference):
    """
    ensure that an encrypted preference cannot be reverted
    """
    register_preference(section='general', preference_name='my_secret', default='i_love_ansible', encrypted=True)
    url = get_relative_url("setting-detail", kwargs={"category_slug": 'general', "preference_name": 'my_secret'})
    response = admin_api_client.delete(url)
    assert response.status_code == 405
    assert response.data["detail"] == "Preference 'my_secret' in category 'general' is encrypted. Action was not performed."


def test_revert_with_readonly_setting(admin_api_client, register_preference):
    """
    ensure that reverting a readonly setting within the specified section is forbidden
    """
    register_preference(section='general', preference_name='iam_read_only', default='i_love_ansible', read_only=True)
    url = get_relative_url("setting-detail", kwargs={"category_slug": 'general', "preference_name": 'iam_read_only'})
    response = admin_api_client.delete(url)
    assert response.status_code == 405
    assert response.data["detail"] == "Preference 'iam_read_only' in category 'general' is read-only. Action was not performed."


def test_get_and_delete_invalid_setting_preference(admin_api_client):
    """
    ensure that we return 404 with messages for GET/DELETE request with invalid setting name
    """
    url = get_relative_url("setting-detail", kwargs={"category_slug": 'proxy', "preference_name": 'hello123'})
    get_response = admin_api_client.get(url)
    assert get_response.status_code == 404
    assert get_response.data['detail'] == "Preference 'hello123' in category 'proxy' was not found. Action was not performed."

    delete_response = admin_api_client.delete(url)
    assert delete_response.status_code == 404
    assert delete_response.data['detail'] == "Preference 'hello123' in category 'proxy' was not found. Action was not performed."
