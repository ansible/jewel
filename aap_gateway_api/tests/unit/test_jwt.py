from aap_gateway_api.utils.jwt_token import create_signed_jwt, decode_signed_jwt


def test_jwt_token_encode_decode(admin_user):
    jwt_token = create_signed_jwt(admin_user)
    decoded = decode_signed_jwt(jwt_token)
    assert decoded["sub"] == admin_user.username
    assert decoded["email"] == admin_user.email
    assert decoded["iss"] == "aap-gateway"
    assert decoded["aud"] == "aap-services"
