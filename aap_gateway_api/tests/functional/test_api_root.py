from django.urls import reverse


def test_api_root_view(unauthenticated_api_client):
    """
    Test the API root view.
    """
    url = reverse("api_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "description" in response.data
    assert response.data["description"] == "AAP Gateway REST API"

    gateway = reverse("api_gateway_root_view")
    assert "gateway" in response.data
    assert response.data["gateway"]["gateway"] == gateway
