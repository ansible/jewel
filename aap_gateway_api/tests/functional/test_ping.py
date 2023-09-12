from django.urls import reverse


def test_ping(unauthenticated_api_client):
    url = reverse("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "pong" in response.data
    assert response.data["pong"] is not None
