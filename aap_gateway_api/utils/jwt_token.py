import logging
from collections import namedtuple
from datetime import datetime, timedelta

import jwt
from ansible_base.rbac.claims import get_claims_hash, get_user_claims, get_user_claims_hashable_form
from ansible_base.resource_registry.models import Resource, service_id
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.db.models import F, Model, OuterRef

from aap_gateway_api.oidc_provider import OIDC_JWT_TTL_CLOCK_SKEW_SECONDS
from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

logger = logging.getLogger('aap.gateway.utils.jwt_token')


def get_jwt_ttl_with_skew(base_ttl_seconds: int) -> int:
    """
    Apply clock skew offset to JWT TTL value.

    Automatically adds OIDC_JWT_TTL_CLOCK_SKEW_SECONDS to the base TTL to ensure
    JWT validity across time synchronization drift between systems.

    Args:
        base_ttl_seconds: Base TTL value from preference (e.g., 300)

    Returns:
        TTL with clock skew added (e.g., 360 = 300 + 60)
    """
    return base_ttl_seconds + OIDC_JWT_TTL_CLOCK_SKEW_SECONDS


def create_signed_jwt(user, resource_api_actions=None):
    """
    Create a signed JWT token for the given user

    The format of the current token is:
    {
        "version": "1",
        "iss": "ansible-issuer",
        "exp": int(due_date.timestamp()),
        "aud": "ansible-services",
        "sub": str(user.resource.ansible_id),
        "service_id": str(user.resource.service_id),
        "user_data": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_superuser": user.is_superuser,
        },
        "claims_hash": "<sha256 hash of claims>",
    }

    Note: The claims data (objects, object_roles, global_roles) is no longer included
    in the JWT token to reduce size. Services should use the JWT claims API endpoint
    (/api/gateway/v1/jwt_claims/<user_ansible_id>) to retrieve the full claims data.
    """

    due_date = datetime.now() + timedelta(seconds=get_preference_value("proxy", "gateway_access_token_expiration"))

    # Get user claims using the new function from django-ansible-base
    user_claims = get_user_claims(user)

    # Generate the claims hash
    hashable_claims = get_user_claims_hashable_form(user_claims)
    claims_hash = get_claims_hash(hashable_claims)

    # Build the JWT payload
    payload = {
        "version": "1",
        "iss": "ansible-issuer",
        "exp": int(due_date.timestamp()),
        "aud": "ansible-services",
        "sub": str(user.resource.ansible_id),
        "service_id": str(service_id()),
        "user_data": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_superuser": user.is_superuser,
        },
        "claims_hash": claims_hash,
    }

    if resource_api_actions:
        payload["resource_api_actions"] = resource_api_actions

    private_key = get_jwt_rsa_key(public=False)
    try:
        token = jwt.encode(payload, private_key, algorithm='RS256')
    except jwt.exceptions.InvalidKeyError:
        _diagnose_key(private_key, public=False)
        raise
    return token


def get_user_object_roles(user: Model) -> list[tuple[str, str, int]]:
    """Returns a list of tuples giving (role name, ansible_id, content_type_id)

    This data is the role name joined with data about the resource"""
    resource_qs = Resource.objects.filter(object_id=OuterRef('object_id'), content_type=OuterRef('content_type')).values('ansible_id')
    assignment_qs = (
        user.role_assignments.filter(content_type__isnull=False)
        .annotate(aid=resource_qs, rd_name=F('role_definition__name'))
        .filter(rd_name__in=settings.ANSIBLE_BASE_JWT_MANAGED_ROLES)
    )
    return [(ra.rd_name, str(ra.aid), ra.content_type_id) for ra in assignment_qs]


def decode_signed_jwt(token):
    public_key = get_jwt_rsa_key(public=True)
    try:
        return jwt.decode(token, public_key, algorithms=['RS256'], audience='ansible-services')
    except jwt.exceptions.InvalidKeyError:
        _diagnose_key(public_key, public=True)
        raise


def _diagnose_key(key_material, public=True):
    """Re-validate a rejected key with cryptography to log the exact reason."""
    key_type = "public" if public else "private"
    if not key_material:
        logger.error("JWT %s key is empty or None. Regenerate the JWT keypair.", key_type)
        return
    if not isinstance(key_material, (str, bytes)):
        logger.error("JWT %s key is not a string (got %s). Check the stored preference value.", key_type, type(key_material).__name__)
        return
    raw = key_material.encode("UTF-8") if isinstance(key_material, str) else key_material
    try:
        if public:
            serialization.load_pem_public_key(raw)
        else:
            serialization.load_pem_private_key(raw, password=None)
    except Exception as diag_exc:
        logger.error("JWT %s key failed cryptography validation: %s", key_type, diag_exc)
    else:
        try:
            from jwt.algorithms import RSAAlgorithm
            RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(key_material)
        except Exception as pyjwt_exc:
            logger.error("JWT %s key passes cryptography validation but PyJWT rejects it: %s", key_type, pyjwt_exc)
        else:
            logger.error(
                "JWT %s key passes both cryptography and PyJWT prepare_key validation "
                "but was still rejected during encode/decode. Check for algorithm mismatch.",
                key_type,
            )


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
