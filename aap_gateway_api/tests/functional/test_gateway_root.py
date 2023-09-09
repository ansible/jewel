from django.urls import reverse


def test_gateway_root_view(unauthenticated_api_client):
    url = reverse("api_gateway_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "v1" in response.data["available_versions"]
