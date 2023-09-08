import pytest

from django.urls import reverse


def test_get_all_settings(admin_api_client):
    url = reverse("setting-section-list", kwargs={"category_slug": "all"})
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
