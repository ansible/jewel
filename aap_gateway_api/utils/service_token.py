from typing import TypedDict

import jwt
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from aap_gateway_api.models import ServiceCluster, ServiceKey, User


class ValidatedToken(TypedDict):
    user: User
    service_cluster: ServiceCluster
    token_data: dict
    key: ServiceKey


def validate_service_token(token) -> ValidatedToken:
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
            options={"verify_signature": False},
            required=["iss", "exp"],
        )["iss"]
    except jwt.exceptions.PyJWTError:
        raise ValidationError(_("Token is not valid a valid JWT."))

    try:
        service_cluster = ServiceCluster.objects.get(service_id=unverified_service_id)
        verified_payload = None
        valid_key = None
        full_data = None

        # Loop through the service's active keys until a key is found that matches the
        # token's signature
        for key in service_cluster.service_keys.filter(is_active=True).order_by("-created"):
            try:
                full_data = jwt.api_jwt.decode_complete(token, key.secret, algorithms=key.algorithm)
                verified_payload = full_data["payload"]
                valid_key = key

                # Double check that the signature verified payload matches the unverified
                # service id.
                assert verified_payload["iss"] == unverified_service_id
                break

            except jwt.exceptions.PyJWTError:
                continue
            except AssertionError:
                raise ValidationError(_("Verified token data does not match unverified data."))

        if verified_payload is None:
            raise ValidationError(_("Unable to validate JWT token against any keys for %(iss)s.") % {"iss": unverified_service_id})

    except ServiceCluster.DoesNotExist:
        raise ValidationError(_("Token issuer %(iss)s does not exist.") % {'iss': unverified_service_id})

    # Check that the user requested in the "sub" claim exists.
    if "sub" in verified_payload:
        try:
            user = User.objects.get(resource__ansible_id=verified_payload["sub"])
        except User.DoesNotExist:
            raise ValidationError(_("Token subject %(sub)s does not exist.") % {'sub': verified_payload['sub']})
    else:
        user = User.all_objects.get(username=settings.SYSTEM_USERNAME)

    return ValidatedToken(
        {
            "user": user,
            "service_cluster": service_cluster,
            "token_data": full_data,
            "key": valid_key,
        }
    )
