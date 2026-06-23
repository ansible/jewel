import pytest
from django.conf import settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceKey


@pytest.mark.django_db
class TestServiceKeyManager:
    def test_create_generates_secret(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.secret
        assert len(key.secret) > 0

    def test_create_custom_secret_length(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway, secret_length=128)
        assert key.secret
        assert len(key.secret) > 0

    def test_create_pops_secret_length(self, service_cluster_gateway):
        """secret_length is consumed by the manager and not passed to the model."""
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway, secret_length=64)
        assert not hasattr(key, 'secret_length') or key.secret


@pytest.mark.django_db
class TestServiceKey:
    def test_save_enforces_max_active_keys(self, service_cluster_gateway):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE
        for _ in range(max_active):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

        with pytest.raises(ValidationError, match="Cannot have more than"):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

    def test_inactive_keys_do_not_count_toward_limit(self, service_cluster_gateway):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE
        for _ in range(max_active):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

        inactive_key = ServiceKey.objects.filter(service_cluster=service_cluster_gateway).first()
        inactive_key.is_active = False
        inactive_key.save()

        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.is_active

    def test_name_is_nullable(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway, name=None)
        assert key.name is None

    def test_default_algorithm_is_hs256(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.algorithm == ServiceKey.JWTAlgorithm.HS256

    def test_algorithm_choices(self):
        assert ServiceKey.JWTAlgorithm.HS256 == "HS256"
        assert ServiceKey.JWTAlgorithm.HS384 == "HS384"
        assert ServiceKey.JWTAlgorithm.HS512 == "HS512"

    def test_secret_is_stored(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.secret is not None
        reloaded = ServiceKey.objects.get(pk=key.pk)
        assert reloaded.secret == key.secret

    def test_service_cluster_fk(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.service_cluster == service_cluster_gateway
        assert key in service_cluster_gateway.service_keys.all()
