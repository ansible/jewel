from ansible_base.lib.utils.response import get_relative_url


def test_ping(unauthenticated_api_client):
    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "pong" in response.data
    assert response.data["pong"] is not None
