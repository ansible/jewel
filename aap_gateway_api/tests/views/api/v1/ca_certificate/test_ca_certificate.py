import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from ansible_base.lib.utils.response import get_relative_url
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from rest_framework import status
from rest_framework.test import APIRequestFactory

from aap_gateway_api.common.authentication import SERVICE_TOKEN_AUTH_STRING
from aap_gateway_api.permissions import ServiceTokenAuthOnly


class TestCACertificateViews:
    def _calculate_sha256(self, pem_data):
        """Helper method to calculate SHA256 with consistent normalization."""
        normalized_pem = pem_data.strip().replace('\r\n', '\n').replace('\r', '\n')
        return hashlib.sha256(normalized_pem.encode('utf-8')).hexdigest()

    @pytest.fixture
    def valid_certificate_pem(self):
        """Generate a valid certificate that's currently active."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Organization"),
                x509.NameAttribute(NameOID.COMMON_NAME, "test.example.com"),
            ]
        )

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(private_key, hashes.SHA256())
        )

        return cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')

    @pytest.fixture
    def expired_certificate_pem(self):
        """Generate an expired certificate."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Expired Test Organization"),
                x509.NameAttribute(NameOID.COMMON_NAME, "expired.example.com"),
            ]
        )

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=365))
            .not_valid_after(now - timedelta(days=1))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(private_key, hashes.SHA256())
        )

        return cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')

    @pytest.fixture
    def invalid_pem_data(self):
        """Invalid PEM data for testing."""
        return "-----BEGIN CERTIFICATE-----\nInvalidCertificateData\n-----END CERTIFICATE-----"

    def test_ca_certificate_create(self, admin_api_client, valid_certificate_pem):
        """Test creating a CA certificate."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"name": "test-ca-cert", "pem_data": valid_certificate_pem, "sha256": sha256, "related_id_reference": "eda-test-1"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'test-ca-cert'
        assert response.data['sha256'] == sha256
        assert response.data['related_id_reference'] == 'eda-test-1'

    def test_ca_certificate_create_invalid_pem(self, admin_api_client, invalid_pem_data):
        """Test creating a CA certificate with invalid PEM data fails."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(invalid_pem_data)
        payload = {"name": "test-invalid-cert", "pem_data": invalid_pem_data, "sha256": sha256, "related_id_reference": "eda-test-2"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'pem_data' in response.data

    def test_ca_certificate_create_expired_cert(self, admin_api_client, expired_certificate_pem):
        """Test creating a CA certificate with expired certificate fails."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(expired_certificate_pem)
        payload = {"name": "test-expired-cert", "pem_data": expired_certificate_pem, "sha256": sha256, "related_id_reference": "eda-test-3"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'pem_data' in response.data

    def test_ca_certificate_list(self, admin_api_client, ca_certificate):
        """Test listing CA certificates."""
        url = get_relative_url('ca_certificate-list')
        response = admin_api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert len(response.data['results']) >= 1

        # Find our test certificate
        cert_found = False
        for cert in response.data['results']:
            if cert['id'] == ca_certificate.id:
                cert_found = True
                assert cert['name'] == ca_certificate.name
                assert 'sha256' in cert
                break
        assert cert_found

    def test_ca_certificate_retrieve(self, admin_api_client, ca_certificate):
        """Test retrieving a specific CA certificate."""
        url = get_relative_url('ca_certificate-detail', kwargs={'pk': ca_certificate.id})
        response = admin_api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == ca_certificate.id
        assert response.data['name'] == ca_certificate.name
        assert 'sha256' in response.data
        assert 'pem_data' in response.data

    def test_ca_certificate_update(self, admin_api_client, ca_certificate, valid_certificate_pem):
        """Test updating a CA certificate."""
        url = get_relative_url('ca_certificate-detail', kwargs={'pk': ca_certificate.id})
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"name": "updated-ca-cert", "pem_data": valid_certificate_pem, "sha256": sha256, "related_id_reference": "eda-updated-1"}
        response = admin_api_client.put(url, payload)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == 'updated-ca-cert'
        assert response.data['related_id_reference'] == 'eda-updated-1'

    def test_ca_certificate_partial_update(self, admin_api_client, ca_certificate):
        """Test partially updating a CA certificate."""
        url = get_relative_url('ca_certificate-detail', kwargs={'pk': ca_certificate.id})
        payload = {"name": "partially-updated-cert"}
        response = admin_api_client.patch(url, payload)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == 'partially-updated-cert'

    def test_ca_certificate_delete(self, admin_api_client, valid_certificate_pem):
        """Test deleting a CA certificate."""
        # First create a certificate to delete
        create_url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"name": "cert-to-delete", "pem_data": valid_certificate_pem, "sha256": sha256, "related_id_reference": "eda-delete-1"}
        create_response = admin_api_client.post(create_url, payload)
        assert create_response.status_code == status.HTTP_201_CREATED
        cert_id = create_response.data['id']

        # Now delete it
        delete_url = get_relative_url('ca_certificate-detail', kwargs={'pk': cert_id})
        response = admin_api_client.delete(delete_url)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's deleted
        get_response = admin_api_client.get(delete_url)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    def test_ca_certificate_permissions_unauthorized(self, unauthenticated_api_client):
        """Test that unauthenticated users cannot access CA certificates."""
        url = get_relative_url('ca_certificate-list')
        response = unauthenticated_api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ca_certificate_permissions_regular_user(self, user_api_client, ca_certificate):
        """Test that regular users cannot access CA certificates."""
        # Test list
        list_url = get_relative_url('ca_certificate-list')
        response = user_api_client.get(list_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Test detail
        detail_url = get_relative_url('ca_certificate-detail', kwargs={'pk': ca_certificate.id})
        response = user_api_client.get(detail_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ca_certificate_sha256_required(self, admin_api_client, valid_certificate_pem):
        """Test that SHA256 is required when creating a CA certificate."""
        url = get_relative_url('ca_certificate-list')
        payload = {"name": "missing-sha256-cert", "pem_data": valid_certificate_pem, "related_id_reference": "eda-missing-1"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'sha256' in response.data

    def test_ca_certificate_name_uniqueness(self, admin_api_client, valid_certificate_pem):
        """Test that CA certificate names must be unique."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"name": "unique-name-test", "pem_data": valid_certificate_pem, "sha256": sha256, "related_id_reference": "eda-unique-1"}

        # Create first certificate
        response1 = admin_api_client.post(url, payload)
        assert response1.status_code == status.HTTP_201_CREATED

        # Try to create second certificate with same name
        response2 = admin_api_client.post(url, payload)
        assert response2.status_code == status.HTTP_400_BAD_REQUEST
        assert 'name' in response2.data

    def test_ca_certificate_filter_by_name(self, admin_api_client, valid_certificate_pem):
        """Test filtering CA certificates by name."""
        # Create a certificate with a specific name
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"name": "filter-test-cert", "pem_data": valid_certificate_pem, "sha256": sha256, "related_id_reference": "eda-filter-1"}
        create_response = admin_api_client.post(url, payload)
        assert create_response.status_code == status.HTTP_201_CREATED

        # Filter by name
        filter_url = f"{url}?name=filter-test-cert"
        response = admin_api_client.get(filter_url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) >= 1

        # Verify the filtered result
        found_cert = None
        for cert in response.data['results']:
            if cert['name'] == 'filter-test-cert':
                found_cert = cert
                break

        assert found_cert is not None
        assert found_cert['name'] == 'filter-test-cert'

    def test_service_token_auth_only_permission_allows_service_token_auth(self):
        """Test that ServiceTokenAuthOnly permission allows requests with ServiceTokenAuthentication."""
        permission = ServiceTokenAuthOnly()
        factory = APIRequestFactory()
        request = factory.get('/ca_certificates/')

        # Mock authenticated user and set auth to SERVICE_TOKEN_AUTH_STRING
        request.user = Mock()
        request.user.is_authenticated = True
        request.auth = SERVICE_TOKEN_AUTH_STRING

        view = Mock()

        # Should allow access
        assert permission.has_permission(request, view) is True

    def test_service_token_auth_only_permission_rejects_other_auth(self):
        """Test that ServiceTokenAuthOnly permission rejects requests without ServiceTokenAuthentication."""
        permission = ServiceTokenAuthOnly()
        factory = APIRequestFactory()
        request = factory.get('/ca_certificates/')

        # Mock authenticated user but with different auth type
        request.user = Mock()
        request.user.is_authenticated = True
        request.auth = "SomeOtherAuthType"

        view = Mock()

        # Should reject access
        assert permission.has_permission(request, view) is False

    def test_service_token_auth_only_permission_rejects_unauthenticated(self):
        """Test that ServiceTokenAuthOnly permission rejects unauthenticated requests."""
        permission = ServiceTokenAuthOnly()
        factory = APIRequestFactory()
        request = factory.get('/ca_certificates/')

        # Mock unauthenticated user
        request.user = Mock()
        request.user.is_authenticated = False
        request.auth = SERVICE_TOKEN_AUTH_STRING

        view = Mock()

        # Should reject access
        assert permission.has_permission(request, view) is False
