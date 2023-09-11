import pytest
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse


def test_jwt_key(unauthenticated_api_client):
    url = reverse("jwt-key-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200

    body = response.content.decode("utf-8")
    assert body.startswith("-----BEGIN PUBLIC KEY-----")
    assert body.endswith("-----END PUBLIC KEY-----\n")


@mock.patch("aap_gateway_api.utils.jwt_token.logger")
def test_jwt_key_bad_key(logger, unauthenticated_api_client, settings, shut_up_logging):
    settings.JWT_KEY = "bad key"
    unauthenticated_api_client.raise_request_exception = False
    url = reverse("jwt-key-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 500
    assert logger.exception.call_count == 1
    assert logger.exception.call_args[0][0] == "Unable to load private key from JWT key"


@mock.patch("aap_gateway_api.utils.jwt_token.logger")
def test_jwt_key_bad_public_key(logger, unauthenticated_api_client, shut_up_logging):
    mock_private_key = MagicMock()
    mock_private_key.public_key().public_bytes.side_effect = Exception("Test Exception")
    with mock.patch(
        "aap_gateway_api.utils.jwt_token.serialization.load_pem_private_key",
        return_value=mock_private_key,
    ):
        unauthenticated_api_client.raise_request_exception = False
        url = reverse("jwt-key-view")
        response = unauthenticated_api_client.get(url)
        assert response.status_code == 500
        assert logger.exception.call_count == 1
        assert (
            logger.exception.call_args[0][0]
            == "Unable to export public key from JWT key"
        )
