import jwt
import pytest

from aap_gateway_api.utils.jwt_token import create_signed_jwt, get_jwt_rsa_key


def test_jwt_token_encode_decode(admin_user):
    jwt_token = create_signed_jwt(admin_user)
    decoded = jwt.decode(
        jwt_token,
        get_jwt_rsa_key(public=True),
        algorithms=["RS256"],
        audience="aap-services",
    )
    assert decoded["sub"] == admin_user.username
    assert decoded["email"] == admin_user.email
    assert decoded["iss"] == "aap-gateway"
    assert decoded["aud"] == "aap-services"
