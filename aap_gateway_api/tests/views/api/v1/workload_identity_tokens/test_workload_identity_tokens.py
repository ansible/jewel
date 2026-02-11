import jwt
import pytest
from ansible_base.lib.utils.response import get_relative_url
from rest_framework import status

from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key, get_jwt_ttl_with_skew
from aap_gateway_api.utils.preferences import get_preference_value


@pytest.fixture
def wit_url():
    return get_relative_url("workload-identity-tokens-view")


@pytest.fixture
def valid_payload():
    return {
        "scope": "dummy_scope",
        "audience": "https://example.com/api",
        "claims": {
            "job_name": "test-job",
            "organization_name": "test-org",
            "project_name": "test-project",
            "job_template_name": "test-template",
        },
    }


class TestWorkloadIdentityTokensAuthentication:
    """Tests for authentication and permission requirements."""

    def test_unauthenticated_request_returns_401(self, unauthenticated_api_client, wit_url, valid_payload):
        """Unauthenticated users cannot access the endpoint."""
        response = unauthenticated_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_regular_user_returns_403(self, user_api_client, wit_url, valid_payload):
        """Non-superuser/non-auditor users are forbidden."""
        response = user_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_superuser_can_access(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Superusers can access the endpoint."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

    def test_platform_auditor_cannot_access(self, platform_auditor_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Platform auditors cannot access the endpoint."""
        response = platform_auditor_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestWorkloadIdentityTokensValidation:
    """Tests for request body validation."""

    @pytest.mark.parametrize(
        "payload, expected_error_field",
        [
            pytest.param({"audience": "https://example.com", "claims": {"job_name": "test-job"}}, "scope", id="missing_scope"),
            pytest.param({"scope": None, "audience": "https://example.com", "claims": {"job_name": "test-job"}}, "scope", id="null_scope"),
            pytest.param({"scope": "", "audience": "https://example.com", "claims": {"job_name": "test-job"}}, "scope", id="empty_scope"),
            pytest.param({"scope": "dummy_scope", "claims": {"job_name": "test-job"}}, "audience", id="missing_audience"),
            pytest.param({"scope": "dummy_scope", "audience": None, "claims": {"job_name": "test-job"}}, "audience", id="null_audience"),
            pytest.param({"scope": "dummy_scope", "audience": "", "claims": {"job_name": "test-job"}}, "audience", id="empty_audience"),
            pytest.param({"scope": "dummy_scope", "audience": "https://example.com"}, "claims", id="missing_claims"),
            pytest.param({"scope": "dummy_scope", "audience": "https://example.com", "claims": {}}, "claims", id="empty_claims"),
        ],
    )
    def test_invalid_payloads_return_400(self, admin_api_client, wit_url, payload, expected_error_field):
        """Parametrized: Various invalid request payloads should cause 400 responses."""
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error_field in response.data

    def test_missing_all_required_fields_returns_400_with_all_errors(self, admin_api_client, wit_url):
        """Request missing all required fields returns 400 with all error messages."""
        payload = {}  # All required fields missing
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "scope" in response.data
        assert "audience" in response.data
        assert "claims" in response.data

    @pytest.mark.parametrize(
        "invalid_claims",
        [
            "not-a-dict",
            ["list", "of", "items"],
            123,
            True,
        ],
    )
    def test_claims_not_dict_returns_400(self, admin_api_client, wit_url, invalid_claims):
        """Request with non-dict claims returns 400."""
        payload = {"scope": "dummy_scope", "audience": "https://example.com", "claims": invalid_claims}
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "claims" in response.data


class TestWorkloadIdentityTokensJWTGeneration:
    """Tests for JWT generation and content."""

    def test_valid_request_returns_jwt(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Valid request returns a signed JWT."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert "jwt" in response.data
        assert isinstance(response.data["jwt"], str)
        # JWT should have 3 parts separated by dots
        assert len(response.data["jwt"].split(".")) == 3

    def test_jwt_contains_standard_claims(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Returned JWT contains jti, iss, sub, aud, exp, iat."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        # Decode without verification to check claims structure
        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        # Check standard claims are present
        for claim in ["jti", "iss", "sub", "aud", "exp", "iat"]:
            assert claim in decoded

    def test_jwt_contains_workload_claims(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Returned JWT includes the custom claims from request."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        # Verify workload claims are included
        assert decoded["job_name"] == "test-job"
        assert decoded["organization_name"] == "test-org"
        assert decoded["project_name"] == "test-project"
        assert decoded["job_template_name"] == "test-template"

    def test_jwt_exp_matches_configured_ttl_preference(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """JWT expiration is set to jwt_default_ttl_seconds preference value from iat."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        # exp should be iat + the configured TTL from the workload_identity preference
        expected_ttl = get_jwt_ttl_with_skew(get_preference_value("workload_identity", "jwt_default_ttl_seconds"))
        assert decoded["exp"] == decoded["iat"] + expected_ttl

    def test_jwt_can_be_verified_with_public_key(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """JWT can be decoded and verified using the gateway public key."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        # This should not raise - JWT is valid and signed correctly
        decoded = jwt.decode(
            response.data["jwt"],
            get_jwt_rsa_key(public=True),
            algorithms=["RS256"],
            audience=valid_payload["audience"],
        )
        assert decoded["job_name"] == "test-job"

    def test_jwt_aud_claim_matches_audience_parameter(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """JWT aud claim matches the audience parameter from the request."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})
        assert decoded["aud"] == valid_payload["audience"]

    @pytest.mark.parametrize(
        "audience",
        [
            "https://example.com/api",
            "urn:my:service",
            "my-service-id",
            "https://vault.example.org",
        ],
    )
    def test_jwt_aud_claim_with_various_audience_values(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys, audience):
        """JWT aud claim correctly reflects various audience values."""
        valid_payload["audience"] = audience
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})
        assert decoded["aud"] == audience

    def test_jwt_sub_claim_format(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """JWT sub claim follows the expected format from generate_sub_claim_from_workload_details."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        expected_sub = "job:test-job:organization:test-org:project:test-project:job_template:test-template"
        assert decoded["sub"] == expected_sub

    @pytest.mark.parametrize(
        "reserved_claim, malicious_value",
        [
            pytest.param("jti", "attacker-controlled-jti", id="jti_overwrite_attempt"),
            pytest.param("exp", 9999999999, id="exp_overwrite_attempt"),
            pytest.param("iat", 0, id="iat_overwrite_attempt"),
            pytest.param("iss", "https://malicious-issuer.com", id="iss_overwrite_attempt"),
            pytest.param("sub", "attacker-controlled-subject", id="sub_overwrite_attempt"),
            pytest.param("aud", "https://wrong-audience.com", id="aud_overwrite_attempt"),
        ],
    )
    def test_reserved_jwt_claims_in_request_are_overwritten(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys, reserved_claim, malicious_value):
        """Reserved JWT claims passed in request claims are overwritten by system-generated values."""
        # Attempt to inject a reserved claim via the claims field
        valid_payload["claims"][reserved_claim] = malicious_value
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        # The reserved claim should NOT have the attacker-controlled value
        assert decoded[reserved_claim] != malicious_value


class TestWorkloadIdentityTokensHTTPMethods:
    """Tests to verify only POST is allowed."""

    def test_get_returns_405(self, admin_api_client, wit_url):
        """GET method is not allowed."""
        response = admin_api_client.get(wit_url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_put_returns_405(self, admin_api_client, wit_url):
        """PUT method is not allowed."""
        response = admin_api_client.put(wit_url, {}, format="json")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_patch_returns_405(self, admin_api_client, wit_url):
        """PATCH method is not allowed."""
        response = admin_api_client.patch(wit_url, {}, format="json")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_delete_returns_405(self, admin_api_client, wit_url):
        """DELETE method is not allowed."""
        response = admin_api_client.delete(wit_url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
