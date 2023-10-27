from unittest import mock
from unittest.mock import MagicMock

from ansible_base.utils.encryption import ENCRYPTED_STRING
from django.urls import reverse

from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key


def test_jwt_key_unauthenticated(unauthenticated_api_client, shut_up_logging):
    url = reverse("jwt-key-view")

    # By default there will be a random key, so this page should always return 200.
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain"


def test_jwt_key_set_via_api(admin_api_client, unauthenticated_api_client, rsa_keypair):
    """
    Test that the JWT key can be set via the API.
    When setting the private key, the public key should be
    automatically extracted and stored as its own preference (proxy__jwt_public_key).

    Note that proxy__jwt_public_key is not a user-editable preference, but its read-only
    property is tested in test_set_readonly_setting in test_settings.py.
    """
    url = reverse("setting-section-list", kwargs={"category_slug": "proxy"})
    response = admin_api_client.put(url, data={"jwt_private_key": rsa_keypair.private})
    assert response.status_code == 200
    assert response.data["jwt_private_key"] == ENCRYPTED_STRING
    assert get_jwt_rsa_key() == rsa_keypair.private

    url = reverse("jwt-key-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert body == rsa_keypair.public
    assert get_jwt_rsa_key(public=True) == rsa_keypair.public


@mock.patch("aap_gateway_api.preferences.update_jwt_public_key")
def test_jwt_key_set_bad_private_key_via_api(update_jwt_public_key, admin_api_client, unauthenticated_api_client, shut_up_logging, rsa_keypair):
    """
    Test what happens when an invalid private key is set via the API.
    """
    url = reverse("setting-section-list", kwargs={"category_slug": "proxy"})
    invalid_private_key = rsa_keypair.private.replace("a", "b").replace("c", "d").replace("e", "f")
    response = admin_api_client.put(url, data={"jwt_private_key": invalid_private_key})
    assert response.status_code == 400
    assert response.data["jwt_private_key"] == "Unable to load private key from PEM key"
    assert update_jwt_public_key.call_count == 0  # Ensure we don't try to update the public key


@mock.patch("aap_gateway_api.utils.jwt_token.logger")
def test_jwt_key_get_bad_public_key(logger, unauthenticated_api_client, shut_up_logging):
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
        assert logger.exception.call_args[0][0] == "Unable to export public key from JWT key"
