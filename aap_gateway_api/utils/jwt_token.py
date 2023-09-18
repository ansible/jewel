import logging
from collections import namedtuple
from datetime import datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

logger = logging.getLogger('aap.gateway.utils.jwt_token')


def create_signed_jwt(user):
    from aap_gateway_api.utils import get_preference_value

    due_date = datetime.now() + timedelta(seconds=get_preference_value("proxy", "gateway_access_token_expiration"))
    teams = [{"name": team.name, "organization": team.organization.name} for team in user.teams.select_related("organization").all()]
    payload = {
        "iss": "aap-gateway",
        "exp": int(due_date.timestamp()),
        "aud": "aap-services",
        "sub": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "is_superuser": user.is_superuser,
        # FIXME: what's the flag for system auditor?
        "is_system_auditor": user.is_superuser,
        "claims": {"organizations": {}, "teams": teams},
    }
    if hasattr(user, 'claim'):
        payload["claims"] = user.claim.data
    token = jwt.encode(payload, get_jwt_rsa_key(), algorithm='RS256')
    return token


def decode_signed_jwt(token):
    return jwt.decode(token, get_jwt_rsa_key(public=True), algorithms=['RS256'], audience='aap-services')


def get_jwt_rsa_key(public=False):
    jwt_key = get_preference_value("proxy", "jwt_private_key", encrypted=False)

    try:
        private_key = serialization.load_pem_private_key(bytes(jwt_key, "UTF-8"), password=None)
    except Exception as e:
        logger.exception("Unable to load private key from JWT key")
        raise e

    if public:
        try:
            return (
                private_key.public_key()
                .public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            )
        except Exception as e:
            logger.exception("Unable to export public key from JWT key")
            raise e

    return jwt_key


def update_jwt_public_key(new_private_key):
    public_key = get_jwt_rsa_key(public=True)
    update_preference_value("proxy", "jwt_public_key", public_key)


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
