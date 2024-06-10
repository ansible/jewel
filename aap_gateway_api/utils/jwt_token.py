import logging
from collections import namedtuple
from datetime import datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

logger = logging.getLogger('aap.gateway.utils.jwt_token')


def create_signed_jwt(user):
    due_date = datetime.now() + timedelta(seconds=get_preference_value("proxy", "gateway_access_token_expiration"))
    teams = [{"name": team["name"], "organization": team["organization__name"]} for team in user.teams.values("name", "organization__name").all()]
    payload = {
        "iss": "ansible-issuer",
        "exp": int(due_date.timestamp()),
        "aud": "ansible-services",
        "sub": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "is_superuser": user.is_superuser,
        "is_system_auditor": user.is_system_auditor,  # NOTE: this only maps to the Platform Auditor role
        "claims": {"organizations": {}, "teams": teams},
    }
    if hasattr(user, 'claim'):
        payload["claims"] = user.claim.data
    token = jwt.encode(payload, get_jwt_rsa_key(public=False), algorithm='RS256')
    return token


def decode_signed_jwt(token):
    return jwt.decode(token, get_jwt_rsa_key(public=True), algorithms=['RS256'], audience='ansible-services')


def get_jwt_rsa_key(public=False):
    if public:
        pub_key = get_preference_value("proxy", "jwt_public_key", encrypted=False)
        # Just in case the public key is not yet loaded into preferences regenerate the key and get it into the cache
        if not pub_key:
            key_to_return = update_jwt_public_key(get_preference_value("proxy", "jwt_private_key", encrypted=False))
        else:
            key_to_return = pub_key
    else:
        key_to_return = get_preference_value("proxy", "jwt_private_key", encrypted=False)

    return key_to_return


def update_jwt_public_key(new_private_key):
    try:
        private_key = serialization.load_pem_private_key(bytes(new_private_key, "UTF-8"), password=None)
    except Exception as e:
        logger.exception("Unable to load private key from JWT key")
        raise e

    try:
        public_key = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        update_preference_value("proxy", "jwt_public_key", public_key)
    except Exception as e:
        logger.exception("Unable to export public key from JWT key")
        raise e

    return public_key


def generate_jwt_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    RSAKeyPair = namedtuple("RSAKeyPair", ["private", "public"])
    return RSAKeyPair(private=private_key_bytes, public=public_key_bytes)
