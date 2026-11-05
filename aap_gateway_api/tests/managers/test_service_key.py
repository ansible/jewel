import pytest

from aap_gateway_api.models import ServiceKey


@pytest.mark.django_db
class TestServiceKeyManager:
    def test_create_generates_secret(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.secret
        assert len(key.secret) > 0

    def test_create_custom_secret_length(self, service_cluster_gateway):
        from unittest.mock import patch

        with patch("aap_gateway_api.managers.service_key.secrets.token_urlsafe", wraps=__import__("secrets").token_urlsafe) as mock_token:
            ServiceKey.objects.create(service_cluster=service_cluster_gateway, secret_length=128)
            mock_token.assert_called_once_with(128)

    def test_create_pops_secret_length(self, service_cluster_gateway):
        """secret_length is consumed by the manager and not passed to the model."""
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway, secret_length=64)
        assert not hasattr(key, 'secret_length')
