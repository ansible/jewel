import pytest

from django.urls import reverse


def test_jwt_key(unauthenticated_api_client):
    url = reverse("jwt-key-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200

    body = response.content.decode("utf-8")
    assert body.startswith("-----BEGIN PUBLIC KEY-----")
    assert body.endswith("-----END PUBLIC KEY-----\n")
