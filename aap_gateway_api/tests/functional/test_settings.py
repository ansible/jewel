import pytest
from django.urls import reverse

from aap_gateway_api.models import Preference


def test_get_all_settings(admin_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert "gateway_token_name" in response.data


def test_get_proxy_settings(admin_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "proxy"})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert "gateway_token_name" in response.data


def test_get_all_settings_unauthenticated(unauthenticated_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 403


def test_set_setting(admin_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})

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
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})
    response = unauthenticated_api_client.put(url, data={"gateway_token_name": "X-FOO-BAR-UNAUTH"})
    assert response.status_code == 403
    assert Preference.objects.filter(name="gateway_token_name").first().value != "X-FOO-BAR-UNAUTH"


def test_set_setting_invalid(admin_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})
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

    url = reverse("setting-section-list", kwargs={"category_slug": "general"})
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
    url = reverse("setting-section-list", kwargs={"category_slug": preference[0]})
    response = admin_api_client.put(url, data={preference[1]: "This should not work"})
    assert response.status_code == 400
    assert str(response.data[preference[1]]) == f"Cannot change read-only setting {preference[1]}"
    assert Preference.objects.filter(name=preference[1]).first().value != "This should not work"
