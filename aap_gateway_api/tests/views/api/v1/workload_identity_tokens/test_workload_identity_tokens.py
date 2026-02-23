import logging
from datetime import UTC, datetime, timedelta
from unittest import mock

import jwt
import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from rest_framework import status
from rest_framework.test import APIClient

from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key, get_jwt_ttl_with_skew
from aap_gateway_api.utils.preferences import get_preference_value


def _create_service_client(user, service_cluster):
    """Helper to create an authenticated service client."""
    service_cluster.service_id = service_id()
    service_cluster.save()
    key = service_cluster.generate_key()

    payload = {
        "sub": str(user.resource.ansible_id),
        "iss": str(service_cluster.service_id),
        "exp": datetime.now(tz=UTC) + timedelta(seconds=60),
    }

    token = jwt.encode(payload, key.secret, key.algorithm)
    return APIClient(headers={"X-ANSIBLE-SERVICE-AUTH": token})


@pytest.fixture
def wit_url():
    return get_relative_url("workload-identity-tokens-view")


@pytest.fixture
def valid_payload():
    return {
        "scope": "aap_controller_automation_job",
        "audience": "https://example.com/api",
        "claims": {
            "aap_controller_job_name": "test-job",
            "aap_controller_organization_name": "test-org",
            "aap_controller_project_name": "test-project",
            "aap_controller_job_template_name": "test-template",
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
            pytest.param({"audience": "https://example.com", "claims": {"aap_controller_job_name": "test-job"}}, "scope", id="missing_scope"),
            pytest.param({"scope": None, "audience": "https://example.com", "claims": {"aap_controller_job_name": "test-job"}}, "scope", id="null_scope"),
            pytest.param({"scope": "", "audience": "https://example.com", "claims": {"aap_controller_job_name": "test-job"}}, "scope", id="empty_scope"),
            pytest.param({"scope": "aap_controller_automation_job", "claims": {"aap_controller_job_name": "test-job"}}, "audience", id="missing_audience"),
            pytest.param(
                {"scope": "aap_controller_automation_job", "audience": None, "claims": {"aap_controller_job_name": "test-job"}},
                "audience",
                id="null_audience",
            ),
            pytest.param(
                {"scope": "aap_controller_automation_job", "audience": "", "claims": {"aap_controller_job_name": "test-job"}},
                "audience",
                id="empty_audience",
            ),
            pytest.param({"scope": "aap_controller_automation_job", "audience": "https://example.com"}, "claims", id="missing_claims"),
            pytest.param({"scope": "aap_controller_automation_job", "audience": "https://example.com", "claims": {}}, "claims", id="empty_claims"),
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
        payload = {"scope": "aap_controller_automation_job", "audience": "https://example.com", "claims": invalid_claims}
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
        assert decoded["aap_controller_job_name"] == "test-job"
        assert decoded["aap_controller_organization_name"] == "test-org"
        assert decoded["aap_controller_project_name"] == "test-project"
        assert decoded["aap_controller_job_template_name"] == "test-template"

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
        assert decoded["aap_controller_job_name"] == "test-job"

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
        """JWT sub claim follows the expected format from scope.generate_sub_claim()."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        decoded = jwt.decode(response.data["jwt"], options={"verify_signature": False})

        expected_sub = "job:test-job:organization:test-org:project:test-project:job_template:test-template"
        assert decoded["sub"] == expected_sub


class TestWorkloadIdentityTokensScopeValidation:
    def test_unknown_scope_returns_400(self, admin_api_client, wit_url):
        """Request with unknown scope returns 400."""
        payload = {
            "scope": "unknown_scope",
            "audience": "https://example.com",
            "claims": {"aap_controller_job_name": "test-job"},
        }
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert response.data["error"] == "Unknown scope: unknown_scope"

    def test_invalid_claims_for_scope_returns_400(self, admin_api_client, wit_url):
        """Request with invalid claims for the scope returns 400."""
        payload = {
            "scope": "aap_controller_automation_job",
            "audience": "https://example.com",
            "claims": {
                "aap_controller_job_name": "test-job",
                "invalid_claim_name": "some-value",
                "another_invalid_claim": "another-value",
            },
        }
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert "invalid_claim_name" in response.data["error"]
        assert "another_invalid_claim" in response.data["error"]

    def test_valid_claims_for_scope_returns_200(self, admin_api_client, wit_url, ensure_jwt_keys):
        """Request with valid claims for the scope returns 200."""
        payload = {
            "scope": "aap_controller_automation_job",
            "audience": "https://example.com",
            "claims": {
                "aap_controller_job_name": "test-job",
                "aap_controller_organization_name": "test-org",
                "aap_controller_project_id": "123",
                "aap_controller_job_id": "456",
            },
        }
        response = admin_api_client.post(wit_url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert "jwt" in response.data

    @pytest.mark.parametrize(
        "reserved_claim, malicious_value",
        [
            pytest.param("jti", "attacker-controlled-jti", id="jti"),
            pytest.param("exp", 9999999999, id="exp"),
            pytest.param("iat", 0, id="iat"),
            pytest.param("iss", "https://malicious-issuer.com", id="iss"),
            pytest.param("sub", "attacker-controlled-subject", id="sub"),
            pytest.param("aud", "https://wrong-audience.com", id="aud"),
        ],
    )
    def test_reserved_claims_are_rejected(self, admin_api_client, wit_url, valid_payload, reserved_claim, malicious_value):
        """Reserved JWT claims in request are rejected as invalid for the scope."""
        valid_payload["claims"][reserved_claim] = malicious_value
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data
        assert reserved_claim in response.data["error"]


class TestWorkloadIdentityTokensServiceAuthorization:

    def test_authorized_service_can_request_scope(self, user, service_cluster_controller, wit_url, valid_payload, ensure_jwt_keys):
        """Controller service can request controller scope."""
        client = _create_service_client(user, service_cluster_controller)
        response = client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert "jwt" in response.data

    @pytest.mark.parametrize(
        "service_type",
        [
            pytest.param("eda", id="eda_service"),
            pytest.param("gateway", id="gateway_service"),
            pytest.param("hub", id="hub_service"),
        ],
    )
    def test_unauthorized_service_cannot_request_scope(self, user, service_type, wit_url, valid_payload, request):
        """Unauthorized services cannot request controller scope."""
        service_cluster = request.getfixturevalue(f"service_cluster_{service_type}")
        client = _create_service_client(user, service_cluster)
        response = client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"] == f"Service '{service_type}' is not authorized for scope 'aap_controller_automation_job'"

    def test_superuser_bypasses_service_authorization(self, admin_api_client, wit_url, valid_payload, ensure_jwt_keys):
        """Superuser (non-service auth) can request any scope without service authorization check."""
        response = admin_api_client.post(wit_url, valid_payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert "jwt" in response.data


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


class TestWorkloadIdentityTokensLogging:
    """Tests for logging during validation."""

    def test_unknown_scope_logs_rejection(self, caplog, admin_api_client, wit_url, valid_payload):
        valid_payload["scope"] = "unknown_scope"
        with caplog.at_level(logging.WARNING, logger="aap.gateway.views.workload_identity_tokens"):
            admin_api_client.post(wit_url, valid_payload, format="json")
            assert "Workload identity token request rejected: Unknown scope: unknown_scope" in caplog.text

    def test_unauthorized_service_logs_audit_details(self, user, service_cluster_eda, wit_url, valid_payload):
        client = _create_service_client(user, service_cluster_eda)
        with mock.patch("aap_gateway_api.views.api.v1.workload_identity_tokens.log_auth_warning") as log_auth_warning:
            client.post(wit_url, valid_payload, format="json")
            log_auth_warning.assert_called_once()
            log_message = log_auth_warning.call_args[0][0]
            assert "Service 'eda' is not authorized" in log_message
            assert f"service_id: {service_cluster_eda.service_id}" in log_message
            assert f"service_cluster: {service_cluster_eda.name}" in log_message

    def test_invalid_claims_logs_rejection(self, caplog, admin_api_client, wit_url, valid_payload):
        valid_payload["claims"]["invalid_claim"] = "value"
        with caplog.at_level(logging.WARNING, logger="aap.gateway.views.workload_identity_tokens"):
            admin_api_client.post(wit_url, valid_payload, format="json")
            assert "Workload identity token request rejected:" in caplog.text
            assert "invalid_claim" in caplog.text
