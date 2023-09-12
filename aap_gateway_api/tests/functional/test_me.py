from django.urls import reverse


def test_me(admin_api_client):
    url = reverse("me-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["results"][0]["username"] == "admin"


def test_me_unauthenticated(unauthenticated_api_client):
    url = reverse("me-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 403
