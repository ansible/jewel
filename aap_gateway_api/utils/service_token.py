from typing import TypedDict

import jwt
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from aap_gateway_api.models import ServiceCluster, ServiceKey, User
from aap_gateway_api.utils.service_id_sync import try_populate_service_id


class ValidatedToken(TypedDict):
    user: User
    service_cluster: ServiceCluster
    token_data: dict
    key: ServiceKey


def _verify_token_signature(token, service_cluster, unverified_service_id):
    """Loops over the cluster's active keys and verifies the JWT signature.

    Args:
        token: The raw JWT string.
        service_cluster: The ServiceCluster whose keys to try.
        unverified_service_id: The iss claim used to cross-check after verification.

    Returns:
        Tuple of (verified_payload, full_data, valid_key).

    Raises:
        ValidationError: If no key validates the token or the iss claim mismatches.
    """
    verified_payload = None
    valid_key = None
    full_data = None

    for key in service_cluster.service_keys.filter(is_active=True).order_by("-created"):
        try:
            full_data = jwt.api_jwt.decode_complete(token, key.secret, algorithms=key.algorithm)
            verified_payload = full_data["payload"]
            valid_key = key
        except jwt.exceptions.PyJWTError:
            continue
        # Cross-check the signature-verified iss against the unverified value. Using an explicit
        # conditional rather than assert so the check cannot be compiled away with -O.
        if verified_payload["iss"] != unverified_service_id:
            raise ValidationError(_("Verified token data does not match unverified data."))
        break

    if verified_payload is None:
        raise ValidationError(_("Unable to validate JWT token against any keys for %(iss)s.") % {"iss": unverified_service_id})

    return verified_payload, full_data, valid_key


def _get_user_from_payload(verified_payload):
    """Resolves the User from the verified JWT payload.

    Args:
        verified_payload: The decoded and verified JWT payload dict.

    Returns:
        The matching User instance.

    Raises:
        ValidationError: If the sub claim references a non-existent user.
    """
    if "sub" in verified_payload:
        try:
            return User.objects.get(resource__ansible_id=verified_payload["sub"])
        except User.DoesNotExist:
            raise ValidationError(_("Token subject %(sub)s does not exist.") % {'sub': verified_payload['sub']})
    return User.all_objects.get(username=settings.SYSTEM_USERNAME)


def validate_service_token(token, required_type=None) -> ValidatedToken:
    """
    Validates that the service token is formatted correctly and signed with a valid key.

    This function check the following:
        1. The provided string is a valid JWT token.
        2. The token has been signed with the secret key from the service that
           claims to have issued it.
        3. The service that issued the token is registered with Gateway.
        4. The token contains the "iss" claims.
        5. The token has not expired.
    """

    # Check the the token is in a valid JWT format and retrieve the service id from the "iss" claim
    try:
        unverified_service_id = jwt.decode(
            token,
            options={"verify_signature": False, "require": ["iss", "exp"]},
        )["iss"]
    except jwt.exceptions.PyJWTError as pje:
        raise ValidationError(_("Token is not a valid JWT: %(exception)s") % {"exception": pje})

    # Look up the cluster by the iss claim, with a lazy fallback for services that were
    # registered after migrate_service_data ran (e.g. a new service added in a later upgrade).
    try:
        service_cluster = ServiceCluster.objects.get(service_id=unverified_service_id)
    except ServiceCluster.DoesNotExist:
        # try_populate_service_id never raises — safe to call on the hot auth path.
        # Returns the cluster directly so we avoid a second DB round-trip.
        service_cluster = try_populate_service_id(str(unverified_service_id))
        if service_cluster is None:
            raise ValidationError(_("Token issuer %(iss)s does not exist.") % {'iss': unverified_service_id})

    verified_payload, full_data, valid_key = _verify_token_signature(token, service_cluster, unverified_service_id)

    token_type = full_data["payload"].get("type", None)
    if required_type != token_type:
        raise ValidationError(
            _("Expected token of type %(required_type)s, but got token of type %(token_type)s") % {"required_type": required_type, "token_type": token_type}
        )

    return ValidatedToken(
        {
            "user": _get_user_from_payload(verified_payload),
            "service_cluster": service_cluster,
            "token_data": full_data,
            "key": valid_key,
        }
    )


def classify_backend(auth_backend):
    """
    > External accounts may be linked to each other as long as they share the same type (LDAP, radius etc.) or to local accounts.

    Thus, we need to know what kind of external account we're dealing with.
    """

    if auth_backend is None:
        return None

    if 'LDAPBackend' in auth_backend:
        return 'ldap'

    if 'RADIUSBackend' in auth_backend:
        return 'radius'

    if 'TACACSPlusBackend' in auth_backend:
        return 'tacacs+'

    # this also covers the AWXModelBackend
    if 'ModelBackend' in auth_backend:
        return 'local'

    if 'PrefixedUserAuthBackend' in auth_backend:
        return 'local'

    return auth_backend
