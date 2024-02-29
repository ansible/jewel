from functools import partial
from unittest import mock

import pytest

from aap_gateway_api.utils.jwt_token import create_signed_jwt, decode_signed_jwt, get_jwt_rsa_key, update_jwt_public_key


def test_jwt_token_encode_decode(admin_user, set_preference, rsa_keypair):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)
    jwt_token = create_signed_jwt(admin_user)
    decoded = decode_signed_jwt(jwt_token)
    assert decoded["sub"] == admin_user.username
    assert decoded["email"] == admin_user.email
    assert decoded["iss"] == "ansible-issuer"
    assert decoded["aud"] == "ansible-services"


def test_jwt_token_update_jwt_public_key_private_key_exception(expected_log):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with expected_log("exception", "Unable to load private key from JWT key"):
        with pytest.raises(Exception):
            update_jwt_public_key('junk')


def test_jwt_token_update_jwt_public_key_public_key_exception(expected_log, rsa_keypair):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with mock.patch('aap_gateway_api.utils.preferences.update_preference_value', side_effect=Exception("Failing on purpose")):
        with expected_log("exception", "Unable to export public key from JWT key"):
            with pytest.raises(Exception):
                update_jwt_public_key(rsa_keypair.private)


def test_jwt_token_get_jwt_rsa_key_private(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    assert get_jwt_rsa_key(public=False) == rsa_keypair.private


def test_jwt_token_get_jwt_rsa_key_public(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    assert get_jwt_rsa_key(public=True) == rsa_keypair.public


def test_jwt_token_get_jwt_rsa_key_public_not_set(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", '')
    assert get_jwt_rsa_key(public=True) == rsa_keypair.public
