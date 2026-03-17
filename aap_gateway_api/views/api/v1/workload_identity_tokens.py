import logging
from datetime import UTC, datetime
from uuid import uuid4

import jwt
from ansible_base.lib.logging import log_auth_event, log_auth_warning
from ansible_base.lib.utils.response import get_fully_qualified_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.workload_identity import SCOPE_REGISTRY, AutomationControllerJobScope
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import DefaultServiceType
from aap_gateway_api.permissions.service_token_only_permission import ServiceTokenAuthOnly
from aap_gateway_api.serializers.workload_identity_tokens import WorkloadIdentityTokenRequestSerializer, WorkloadIdentityTokenResponseSerializer
from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key, get_jwt_ttl_with_skew
from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger("aap.gateway.views.workload_identity_tokens")

SCOPE_SERVICE_AUTHORIZATION = {
    AutomationControllerJobScope.name: DefaultServiceType.CONTROLLER.value,
}

WIT_REQUEST_REJECTED_MSG = "Workload identity token request rejected: %s"


def _validate_claims_for_scope(scope_class, claims: dict) -> set[str]:
    """
    Validate that all claims in the request are valid for the specified scope.

    This function checks that the provided claims align with the scope definition.
    It ensures that only claims defined in the scope's list_claims() method are
    included in the request.

    Reserved JWT claims (jti, exp, iat, iss, sub, aud) will be rejected because they
    are not included in any scope's list_claims() definition. The gateway is responsible
    for setting these values during JWT construction.

    Args:
        scope_class: The scope class from SCOPE_REGISTRY
        claims: Dictionary of claim names and values from the request

    Returns:
        Set of invalid claim names (empty set if all claims are valid)
    """
    allowed_claims = set(scope_class.list_claims())
    provided_claims = set(claims.keys())

    return provided_claims - allowed_claims


class WorkloadIdentityTokensView(AnsibleBaseView):
    # WIT API can be accessed by ServiceTokenAuthentication only
    # WIT API cannot be accessed by other users or authentication types
    custom_action_label = "create"  # For permission checking
    permission_classes = [ServiceTokenAuthOnly]
    schema = None  # Exclude from OpenAPI schema - internal service-to-service API

    # WIT API accepts only POST requests
    def post(self, request):
        """
        This POST endpoint will serve JWT tokens for workload identity based on a set of claims received as parameters in the request.
        """
        # WIT accepts a JSON request body containing the fields claims and scope. Claims in the body must be included in the issued JWT
        request_serializer = WorkloadIdentityTokenRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            logger.warning("Workload identity token request failed validation: %s", request_serializer.errors)
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = request_serializer.validated_data
        workload_claims = validated_data["claims"]
        audience = validated_data["audience"]
        scope = validated_data["scope"]
        workload_ttl_seconds = validated_data.get("workload_ttl_seconds")

        # [AAP-62528] Check that the requested scope is valid against the well-known oidc GW endpoints.

        # Validate scope exists
        scope_class = SCOPE_REGISTRY.get(scope)
        if scope_class is None:
            error_msg = f"Unknown scope: {scope}"
            logger.warning(WIT_REQUEST_REJECTED_MSG, error_msg)
            return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

        # Validate service is authorized for scope.
        # ServiceTokenAuthOnly ensures only service-token-authenticated requests reach here.
        service_cluster = getattr(request, 'service_cluster', None)
        if not service_cluster:
            logger.error("Workload identity token request rejected: missing service_cluster")
            return Response({"error": "Service authentication required"}, status=status.HTTP_403_FORBIDDEN)

        service_type_name = service_cluster.service_type.name
        if SCOPE_SERVICE_AUTHORIZATION.get(scope) != service_type_name:
            error_msg = f"Service '{service_type_name}' is not authorized for scope '{scope}'"
            log_auth_warning(
                f"Workload identity token request rejected: {error_msg} (service_id: {service_cluster.service_id}, service_cluster: {service_cluster.name})"
            )
            return Response({"error": error_msg}, status=status.HTTP_403_FORBIDDEN)

        # Validate claims align with scope
        if invalid_claims := _validate_claims_for_scope(scope_class, workload_claims):
            error_msg = f"Invalid claims for scope '{scope}': {', '.join(sorted(invalid_claims))}"
            logger.warning(WIT_REQUEST_REJECTED_MSG, error_msg)
            return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch the gateway common private key for signing the JWT
        gw_private_key = get_jwt_rsa_key()

        # Workload TTL takes priority; serializer enforces min_value=1 and max_value=86400 when present.
        base_ttl = workload_ttl_seconds or get_preference_value("workload_identity", "jwt_default_ttl_seconds", encrypted=False)
        # Always add clock skew offset to ensure token validity across time drift
        jwt_ttl_seconds = get_jwt_ttl_with_skew(base_ttl)

        logger.debug(
            "JWT TTL calculated: workload_ttl=%s, base_ttl=%s, final_ttl_with_skew=%s",
            workload_ttl_seconds,
            base_ttl,
            jwt_ttl_seconds,
        )
        jwt_issuance_timestamp = datetime.now(tz=UTC).timestamp()
        # WIT issues a JWT with exp claim set to current time plus the configured TTL preference
        # WIT sets other standard claims https://datatracker.ietf.org/doc/html/rfc7519#section-4.1 to reasonable values
        # WIT issues a JWT with the iss claim matching the OIDC Discovery configuration in AAP-43413
        jwt_default_claims = {
            "jti": str(uuid4()),
            "iss": get_fully_qualified_url("oauth2_provider:oauth_authorization_root_view"),
            "sub": scope_class.generate_sub_claim(workload_claims),
            "aud": audience,
            "exp": jwt_issuance_timestamp + jwt_ttl_seconds,
            "iat": jwt_issuance_timestamp,
        }

        # WIT API issues a JWT with the RS256 algorithm, signed by the aap-gateway private key get_jwt_rsa_key
        signed_jwt = jwt.encode({**workload_claims, **jwt_default_claims}, gw_private_key, algorithm="RS256")

        log_auth_event(
            f"Workload identity token issued to user '{request.user}' for scope '{scope}': "
            f"jti={jwt_default_claims['jti']}, sub={jwt_default_claims['sub']}, "
            f"aud={jwt_default_claims['aud']}, exp={jwt_default_claims['exp']}"
        )

        # Serialize the response using the response serializer
        response_serializer = WorkloadIdentityTokenResponseSerializer(data={"jwt": signed_jwt})
        response_serializer.is_valid(raise_exception=True)
        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
