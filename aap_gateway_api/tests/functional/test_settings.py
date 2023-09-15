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
    "preference_type, default, value, err_substring",
    [
        # NOTE: If you add cases to this matrix, add them to in unit/test_preferences.py, too.
        ("string", "foo", 1234, None),  # Apparently this gets coerced to a string
        ("string", "foo", True, None),  # Apparently this gets coerced to a string
        ("bool", False, "true", "true is not a boolean"),
        ("bool", False, 1, "1 is not a boolean"),
        ("int", 0, "not an int", "IntSerializer can only serialize int values"),
        ("int", 0, False, "IntSerializer can only serialize int values"),
        ("url", "https://example.com", 1337, "1337 is not a valid URL"),
    ],
)
def test_set_setting_bad_type(admin_api_client, register_preference, preference_type, default, value, err_substring):
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
        assert response.data["bad_type"].code == "invalid"
        assert str(response.data["bad_type"]) == err_substring
