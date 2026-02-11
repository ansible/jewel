import logging
from datetime import UTC, datetime
from uuid import uuid4

import jwt
from ansible_base.lib.utils.response import get_fully_qualified_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.utils.views.permissions import IsSuperuser
from ansible_base.lib.workload_identity.workload_identity_tokens import WorkloadIdentityTokenRequestSerializer, WorkloadIdentityTokenResponseSerializer
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.permissions.service_token_only_permission import ServiceTokenAuthOnly
from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key, get_jwt_ttl_with_skew
from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger("aap.gateway.views.workload_identity_tokens")


TARGET_CLAIM_NAMES_TO_SUB_STUBS = {
    "job_name": "job",
    "organization_name": "organization",
    "project_name": "project",
    "job_template_name": "job_template",
}


def generate_sub_claim_from_workload_details(workload_details: dict) -> str:
    """
    Given a dictionary with the details of a workload, generates a sub claim string with the following format:
    "job:<job_name>:organization:<organization_name>:project:<project_name>:job_template:<job_template_name>"

    Note: The specified claim names are included in the output sub claim value even if they
    are empty. Claim validation is expected to take care of doing these checks before this
    function is called.

    Args:
        workload_details: A dictionary containing the workload details
    Returns:
        A string containing the sub claim string
    """
    return ":".join([f"{TARGET_CLAIM_NAMES_TO_SUB_STUBS[key]}:{workload_details.get(key, '')}" for key in TARGET_CLAIM_NAMES_TO_SUB_STUBS.keys()])


class WorkloadIdentityTokensView(AnsibleBaseView):
    # WIT API can be accessed by ServiceTokenAuthentication (and superuser)
    # WIT API cannot be accessed by other users or authentication types
    custom_action_label = "create"  # For permission checking
    permission_classes = [OAuth2ScopePermission, IsSuperuser | ServiceTokenAuthOnly]

    # WIT API accepts only POST requests
    @extend_schema(
        request=WorkloadIdentityTokenRequestSerializer,
        responses=WorkloadIdentityTokenResponseSerializer,
        extensions={"x-ai-description": "Issue a signed JWT token for workload identity based on provided claims"},
    )
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

        # [AAP-62528] Check that the requested scope is valid against the well-known oidc GW endpoints.
        # For now we just pass along the received value (future issues)

        # JWTs issued by WIT will not validate scopes for claims initially. Stories in other epics will expand this.
        # [AAP-62657] Filter out claims not included in the requested scopes (once default scope is implemented in DAB)
        # [AAP-62528] Add validation of the received claims (future issues)

        # Fetch the gateway common private key for signing the JWT
        gw_private_key = get_jwt_rsa_key()

        # WIT issues a JWT with exp claim set to current time plus the configured TTL preference
        # WIT sets other standard claims https://datatracker.ietf.org/doc/html/rfc7519#section-4.1 to reasonable values
        # WIT issues a JWT with the iss claim matching the OIDC Discovery configuration in AAP-43413
        jwt_ttl_seconds = get_jwt_ttl_with_skew(get_preference_value("workload_identity", "jwt_default_ttl_seconds", encrypted=False))
        jwt_issuance_timestamp = datetime.now(tz=UTC).timestamp()
        jwt_default_claims = {
            "jti": str(uuid4()),
            "iss": get_fully_qualified_url("oauth2_provider:oauth_authorization_root_view"),
            "sub": generate_sub_claim_from_workload_details(workload_claims),
            "aud": audience,
            "exp": jwt_issuance_timestamp + jwt_ttl_seconds,
            "iat": jwt_issuance_timestamp,
        }

        # WIT API issues a JWT with the RS256 algorithm, signed by the aap-gateway private key get_jwt_rsa_key
        signed_jwt = jwt.encode({**workload_claims, **jwt_default_claims}, gw_private_key, algorithm="RS256")

        logger.info(
            "Workload identity token issued: jti=%s, sub=%s, aud=%s, exp=%s",
            jwt_default_claims["jti"],
            jwt_default_claims["sub"],
            jwt_default_claims["aud"],
            jwt_default_claims["exp"],
        )

        # Serialize the response using the response serializer
        response_serializer = WorkloadIdentityTokenResponseSerializer(data={"jwt": signed_jwt})
        response_serializer.is_valid(raise_exception=True)
        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
