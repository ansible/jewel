from django.urls import reverse


def test_gateway_v1_view(unauthenticated_api_client):
    url = reverse("api_gateway_v1_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200

    # Check a few keys that should be present in the response
    keys = ("environment", "me", "ping")
    for key in keys:
        assert key in response.data.keys()
