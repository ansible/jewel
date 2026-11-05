import pytest
from django.conf import settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceKey


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

        # Deactivating one should allow creating another
        inactive_key = ServiceKey.objects.filter(service_cluster=service_cluster_gateway, is_active=True).first()
        inactive_key.is_active = False
        inactive_key.save()

        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        assert key.is_active

    def test_saving_existing_active_key_at_limit_succeeds(self, service_cluster_gateway):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE
        keys = [ServiceKey.objects.create(service_cluster=service_cluster_gateway) for _ in range(max_active)]

        keys[0].refresh_from_db()
        keys[0].name = "updated-key"
        keys[0].save()

        keys[0].refresh_from_db()
        assert keys[0].name == "updated-key"

    @pytest.mark.parametrize("field", ["algorithm", "secret", "service_cluster"])
    def test_save_rejects_changes_to_write_once_fields(self, field, service_cluster_eda, service_cluster_gateway):
        key = ServiceKey.objects.create(service_cluster=service_cluster_gateway)
        key.refresh_from_db()
        replacement_values = {
            "algorithm": ServiceKey.JWTAlgorithm.HS512,
            "secret": "replacement-secret",
            "service_cluster": service_cluster_eda,
        }
        setattr(key, field, replacement_values[field])

        with pytest.raises(ValidationError, match="cannot be changed after creation"):
            key.save()

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
