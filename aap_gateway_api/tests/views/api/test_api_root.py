import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.test import override_settings

ROOT_URL_NAMES = ["api_root_view", "api_gateway_root_view", "api_gateway_v1_root_view"]


def test_api_root_view(unauthenticated_api_client):
    """
    Test the API root view.
    """
    url = get_relative_url("api_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "description" in response.data
    assert response.data["description"] == "REST API"

    gateway = get_relative_url("api_gateway_root_view")
    assert "apis" in response.data
    assert response.data["apis"]["gateway"] == gateway


@pytest.mark.parametrize("url_name", ROOT_URL_NAMES)
def test_api_roots_allow_anonymous_by_default(unauthenticated_api_client, url_name):
    response = unauthenticated_api_client.get(get_relative_url(url_name))

    assert response.status_code == 200


@pytest.mark.parametrize("url_name", ROOT_URL_NAMES)
@override_settings(API_ROOTS_REQUIRE_AUTHENTICATION=True)
def test_api_roots_require_authentication_when_enabled(unauthenticated_api_client, url_name):
    response = unauthenticated_api_client.get(get_relative_url(url_name))

    assert response.status_code == 401


@pytest.mark.parametrize("url_name", ROOT_URL_NAMES)
@pytest.mark.parametrize("client_fixture", ["admin_api_client", "user_api_client"])
@override_settings(API_ROOTS_REQUIRE_AUTHENTICATION=True)
def test_api_roots_visible_to_authenticated_users(request, client_fixture, url_name):
    client = request.getfixturevalue(client_fixture)
    response = client.get(get_relative_url(url_name))

    assert response.status_code == 200
