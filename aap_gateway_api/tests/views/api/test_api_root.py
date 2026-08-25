from ansible_base.lib.utils.response import get_relative_url


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
