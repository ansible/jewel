from aap_gateway_api.utils.jwt_token import create_signed_jwt, decode_signed_jwt


def test_jwt_token_encode_decode(admin_user, set_preference, rsa_keypair):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)
    jwt_token = create_signed_jwt(admin_user)
    decoded = decode_signed_jwt(jwt_token)
    assert decoded["sub"] == admin_user.username
    assert decoded["email"] == admin_user.email
    assert decoded["iss"] == "ansible-issuer"
    assert decoded["aud"] == "ansible-services"
