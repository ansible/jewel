import pytest
from django.urls import reverse


@pytest.mark.parametrize("category_slug", ["all", "proxy"])
def test_settings_list_permissions(user_api_client, category_slug):
    url = reverse("setting-section-list", kwargs={"category_slug": category_slug})
    response = user_api_client.get(url)
    assert response.status_code == 403


@pytest.mark.parametrize("category_slug", ["all", "configuration"])
def test_settings_change_permissions(user_api_client, category_slug):
    url = reverse("setting-section-list", kwargs={"category_slug": category_slug})

    response = user_api_client.put(url, data={"DEFAULT_PAGE_SIZE": 10})
    assert response.status_code == 403
