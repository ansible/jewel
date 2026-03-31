import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from ansible_base.lib.utils.response import get_relative_url
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from rest_framework import status

from aap_gateway_api.serializers.ca_certificate import CACertificateSerializer


class TestCACertificateSerializer:
    def _calculate_sha256(self, pem_data):
        """Helper method to calculate SHA256 with consistent normalization."""
        normalized_pem = pem_data.strip().replace('\r\n', '\n').replace('\r', '\n')
        return hashlib.sha256(normalized_pem.encode('utf-8')).hexdigest()

    @pytest.fixture
    def valid_certificate_pem(self):
        """Generate a valid certificate that's currently active."""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
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
            .not_valid_before(now - timedelta(days=1))  # Valid since yesterday
            .not_valid_after(now + timedelta(days=365))  # Valid for a year
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
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
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
            .not_valid_before(now - timedelta(days=365))  # Was valid a year ago
            .not_valid_after(now - timedelta(days=1))  # Expired yesterday
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

    @pytest.fixture
    def certificate_chain_pem(self):
        """Generate a certificate chain with root CA and intermediate CA."""
        now = datetime.now(timezone.utc)

        # Generate Root CA private key
        root_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create Root CA certificate
        root_subject = root_issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Root CA Organization"),
                x509.NameAttribute(NameOID.COMMON_NAME, "Root CA"),
            ]
        )

        root_cert = (
            x509.CertificateBuilder()
            .subject_name(root_subject)
            .issuer_name(root_issuer)
            .public_key(root_private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))  # 10 years
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=1),  # Can sign one level
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    key_encipherment=False,
                    key_agreement=False,
                    data_encipherment=False,
                    content_commitment=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(root_private_key, hashes.SHA256())
        )

        # Generate Intermediate CA private key
        intermediate_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create Intermediate CA certificate (signed by Root CA)
        intermediate_subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Intermediate CA Organization"),
                x509.NameAttribute(NameOID.COMMON_NAME, "Intermediate CA"),
            ]
        )

        intermediate_cert = (
            x509.CertificateBuilder()
            .subject_name(intermediate_subject)
            .issuer_name(root_subject)  # Issued by Root CA
            .public_key(intermediate_private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1825))  # 5 years
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),  # Can sign end entities only
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    key_encipherment=False,
                    key_agreement=False,
                    data_encipherment=False,
                    content_commitment=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(root_private_key, hashes.SHA256())  # Signed by Root CA
        )

        # Combine certificates into a chain (intermediate first, then root)
        intermediate_pem = intermediate_cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')
        root_pem = root_cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')

        return intermediate_pem + root_pem

    @pytest.fixture
    def mixed_validity_certificate_chain_pem(self):
        """Generate a certificate chain where one cert is expired and one is valid."""
        now = datetime.now(timezone.utc)

        # Generate valid Root CA
        root_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        root_subject = root_issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Valid Root CA"),
                x509.NameAttribute(NameOID.COMMON_NAME, "Valid Root CA"),
            ]
        )

        valid_cert = (
            x509.CertificateBuilder()
            .subject_name(root_subject)
            .issuer_name(root_issuer)
            .public_key(root_private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))  # Valid
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(root_private_key, hashes.SHA256())
        )

        # Generate expired certificate
        expired_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        expired_subject = expired_issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "NC"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Durham"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Expired CA"),
                x509.NameAttribute(NameOID.COMMON_NAME, "Expired CA"),
            ]
        )

        expired_cert = (
            x509.CertificateBuilder()
            .subject_name(expired_subject)
            .issuer_name(expired_issuer)
            .public_key(expired_private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=365))
            .not_valid_after(now - timedelta(days=1))  # Expired
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(expired_private_key, hashes.SHA256())
        )

        # Combine certificates (expired first, then valid)
        expired_pem = expired_cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')
        valid_pem = valid_cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')

        return expired_pem + valid_pem

    def test_ca_certificate_get(self, admin_api_client, ca_certificate):
        url = get_relative_url('ca_certificate-detail', kwargs={'pk': ca_certificate.id})
        response = admin_api_client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_ca_certificate_post_valid_cert(self, admin_api_client, valid_certificate_pem):
        """Test creating CA certificate with valid certificate."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(valid_certificate_pem)
        payload = {"pem_data": valid_certificate_pem, "name": "test-valid-cert", "sha256": sha256, "related_id_reference": "eda-1"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'test-valid-cert'
        assert response.data['sha256'] == sha256

    def test_ca_certificate_post_expired_cert(self, admin_api_client, expired_certificate_pem):
        """Test creating CA certificate with expired certificate should fail."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(expired_certificate_pem)
        payload = {"pem_data": expired_certificate_pem, "name": "test-expired-cert", "sha256": sha256, "related_id_reference": "eda-2"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'pem_data' in response.data
        assert 'expired' in str(response.data['pem_data']).lower()

    def test_ca_certificate_post_invalid_pem(self, admin_api_client, invalid_pem_data):
        """Test creating CA certificate with invalid PEM data should fail."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(invalid_pem_data)
        payload = {"pem_data": invalid_pem_data, "name": "test-invalid-pem", "sha256": sha256, "related_id_reference": "eda-4"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'pem_data' in response.data
        assert 'invalid' in str(response.data['pem_data']).lower()

    def test_ca_certificate_serializer_valid_cert(self, valid_certificate_pem):
        """Test serializer directly with valid certificate."""
        sha256 = self._calculate_sha256(valid_certificate_pem)
        data = {'name': 'test-serializer-valid', 'pem_data': valid_certificate_pem, 'sha256': sha256, 'related_id_reference': 'eda-serializer-1'}

        serializer = CACertificateSerializer(data=data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

        validated_data = serializer.validated_data
        assert validated_data['sha256'] == sha256

    def test_ca_certificate_serializer_expired_cert(self, expired_certificate_pem):
        """Test serializer directly with expired certificate."""
        sha256 = self._calculate_sha256(expired_certificate_pem)
        data = {'name': 'test-serializer-expired', 'pem_data': expired_certificate_pem, 'sha256': sha256, 'related_id_reference': 'eda-serializer-2'}

        serializer = CACertificateSerializer(data=data)
        assert not serializer.is_valid()
        assert 'pem_data' in serializer.errors
        assert 'expired' in str(serializer.errors['pem_data']).lower()

    def test_ca_certificate_serializer_invalid_pem(self, invalid_pem_data):
        """Test serializer directly with invalid PEM data."""
        sha256 = self._calculate_sha256(invalid_pem_data)
        data = {'name': 'test-serializer-invalid', 'pem_data': invalid_pem_data, 'sha256': sha256, 'related_id_reference': 'eda-serializer-4'}

        serializer = CACertificateSerializer(data=data)
        assert not serializer.is_valid()
        assert 'pem_data' in serializer.errors
        assert 'invalid' in str(serializer.errors['pem_data']).lower()

    def test_ca_certificate_post_certificate_chain(self, admin_api_client, certificate_chain_pem):
        """Test creating CA certificate with a valid certificate chain (multiple certificates)."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(certificate_chain_pem)
        payload = {"pem_data": certificate_chain_pem, "name": "test-cert-chain", "sha256": sha256, "related_id_reference": "eda-chain-1"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'test-cert-chain'
        assert response.data['sha256'] == sha256

        # Verify the certificate chain contains multiple certificates
        from cryptography import x509

        certificates = x509.load_pem_x509_certificates(certificate_chain_pem.encode('utf-8'))
        assert len(certificates) == 2  # Should have 2 certificates in the chain

    def test_ca_certificate_post_mixed_validity_chain(self, admin_api_client, mixed_validity_certificate_chain_pem):
        """Test creating CA certificate with mixed validity chain should fail."""
        url = get_relative_url('ca_certificate-list')
        sha256 = self._calculate_sha256(mixed_validity_certificate_chain_pem)
        payload = {"pem_data": mixed_validity_certificate_chain_pem, "name": "test-mixed-chain", "sha256": sha256, "related_id_reference": "eda-mixed-1"}
        response = admin_api_client.post(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'pem_data' in response.data
        assert 'expired' in str(response.data['pem_data']).lower()

    def test_ca_certificate_serializer_certificate_chain(self, certificate_chain_pem):
        """Test serializer directly with valid certificate chain."""
        sha256 = self._calculate_sha256(certificate_chain_pem)
        data = {'name': 'test-serializer-chain', 'pem_data': certificate_chain_pem, 'sha256': sha256, 'related_id_reference': 'eda-serializer-chain-1'}

        serializer = CACertificateSerializer(data=data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

        validated_data = serializer.validated_data
        assert validated_data['sha256'] == sha256

        # Verify the certificate chain can be parsed
        from cryptography import x509

        certificates = x509.load_pem_x509_certificates(certificate_chain_pem.encode('utf-8'))
        assert len(certificates) == 2  # Should have 2 certificates in the chain

        # Verify both certificates are CA certificates
        for cert in certificates:
            basic_constraints = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.BASIC_CONSTRAINTS)
            assert basic_constraints.value.ca is True

    def test_ca_certificate_serializer_mixed_validity_chain(self, mixed_validity_certificate_chain_pem):
        """Test serializer directly with mixed validity certificate chain."""
        sha256 = self._calculate_sha256(mixed_validity_certificate_chain_pem)
        data = {
            'name': 'test-serializer-mixed-chain',
            'pem_data': mixed_validity_certificate_chain_pem,
            'sha256': sha256,
            'related_id_reference': 'eda-serializer-mixed-1',
        }

        serializer = CACertificateSerializer(data=data)
        assert not serializer.is_valid()
        assert 'pem_data' in serializer.errors
        assert 'expired' in str(serializer.errors['pem_data']).lower()

        # Verify the chain contains multiple certificates with mixed validity
        from cryptography import x509

        certificates = x509.load_pem_x509_certificates(mixed_validity_certificate_chain_pem.encode('utf-8'))
        assert len(certificates) == 2  # Should have 2 certificates in the chain

    def test_certificate_chain_validation_logic(self, certificate_chain_pem):
        """Test that certificate chain validation checks ALL certificates in the chain."""
        from datetime import datetime, timezone

        from cryptography import x509

        # Parse the certificate chain
        certificates = x509.load_pem_x509_certificates(certificate_chain_pem.encode('utf-8'))
        assert len(certificates) == 2

        # Verify all certificates are currently valid
        now = datetime.now(timezone.utc)
        for i, cert in enumerate(certificates):
            assert cert.not_valid_before_utc <= now, f"Certificate {i} not yet valid"
            assert cert.not_valid_after_utc > now, f"Certificate {i} has expired"

        # Test that the serializer validates all certificates
        sha256 = self._calculate_sha256(certificate_chain_pem)
        data = {'name': 'test-chain-validation', 'pem_data': certificate_chain_pem, 'sha256': sha256, 'related_id_reference': 'eda-validation-1'}

        serializer = CACertificateSerializer(data=data)
        assert serializer.is_valid(), f"Serializer should accept valid chain: {serializer.errors}"
