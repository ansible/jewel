from ansible_base.lib.utils.response import get_relative_url


def test_gateway_v1_view(unauthenticated_api_client):
    url = get_relative_url("api_gateway_v1_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200

    # Check a few keys that should be present in the response
    keys = ("me", "ping")
    for key in keys:
        assert key in response.data.keys()
