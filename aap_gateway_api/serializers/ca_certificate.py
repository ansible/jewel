from datetime import datetime, timezone

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from rest_framework import serializers

from aap_gateway_api.models import CACertificate


class CertificateChainPemField(serializers.CharField):
    """
    A serializer field for validating PEM certificate chain data.
    """

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        certificates = []
        try:
            # load_pem_x509_certificates expects bytes
            certificates = x509.load_pem_x509_certificates(data.encode('utf-8'))
        except (ValueError, UnsupportedAlgorithm) as e:
            # Catch exceptions from cryptography and raise a DRF ValidationError
            raise serializers.ValidationError(f"Invalid PEM certificate data: {e}")
        # We might have a chain of certificates, check expiry of each
        for certificate in certificates:
            now = datetime.now(timezone.utc)
            if now > certificate.not_valid_after_utc:
                raise serializers.ValidationError(f"Certificate has expired: {certificate.not_valid_after_utc}")
        return data


class CACertificateSerializer(NamedCommonModelSerializer):
    pem_data = CertificateChainPemField(required=True)
    sha256 = serializers.CharField(required=True)

    class Meta:
        model = CACertificate
        fields = NamedCommonModelSerializer.Meta.fields + ['pem_data', 'sha256', 'related_id_reference']
