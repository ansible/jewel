from ansible_base.lib.utils.response import get_relative_url


def test_me(admin_api_client):
    url = get_relative_url("me-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["results"][0]["username"] == "admin"


def test_me_unauthenticated(unauthenticated_api_client):
    url = get_relative_url("me-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401
