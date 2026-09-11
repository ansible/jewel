import pytest
from django.conf import settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceKey


@pytest.mark.django_db
class TestServiceKey:
    def test_save_enforces_max_active_keys(self, service_cluster_gateway):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE
        # save() uses count() - 1 >= max_active to account for re-saves of
        # existing objects, so we need max_active + 1 existing active keys
        # before the next create is rejected.
        for _ in range(max_active + 1):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

        with pytest.raises(ValidationError, match="Cannot have more than"):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

    def test_inactive_keys_do_not_count_toward_limit(self, service_cluster_gateway):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE
        # Fill to max_active + 1 so the limit is reached
        for _ in range(max_active + 1):
            ServiceKey.objects.create(service_cluster=service_cluster_gateway)

        # Deactivating one should allow creating another
        inactive_key = ServiceKey.objects.filter(service_cluster=service_cluster_gateway, is_active=True).first()
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

    def test_secret_persists_across_reload(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.secret is not None
        reloaded = ServiceKey.objects.get(pk=key.pk)
        assert reloaded.secret is not None
        assert len(reloaded.secret) > 0

    def test_service_cluster_fk(self, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.service_cluster == service_cluster_gateway
        assert key in service_cluster_gateway.service_keys.all()
