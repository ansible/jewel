from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.serializers.service_key import ServiceKeySerializer


@pytest.mark.django_db
class TestServiceKeySerializer:
    def test_meta_fields_include_service_key_fields(self):
        expected = ["service_cluster", "is_active", "algorithm", "secret"]
        for field_name in expected:
            assert field_name in ServiceKeySerializer.Meta.fields

    def test_validate_is_active(self, service_key_factory, service_cluster_eda):
        key1 = service_key_factory(service_cluster_eda)
        key2 = service_key_factory(service_cluster_eda)
        _ = service_key_factory(service_cluster_eda)
        key2.refresh_from_db()

        # At this point, key 3 is the only active key.

        with override_settings(MAX_ACTIVE_KEYS_PER_SERVICE=2):
            serializer = ServiceKeySerializer(instance=key1, data={"is_active": True}, partial=True)
            serializer.is_valid(raise_exception=True)

            key1.is_active = True
            key1.save()

            # We now have 2 active keys so trying to activate a third should fail
            serializer = ServiceKeySerializer(instance=key2, data={"is_active": True}, partial=True)
            with pytest.raises(ValidationError, match="Cannot activate this key"):
                serializer.is_valid(raise_exception=True)

        # Validate that increasing the setting now allows for key2 to be saved
        with override_settings(MAX_ACTIVE_KEYS_PER_SERVICE=3):
            serializer = ServiceKeySerializer(instance=key2, data={"is_active": True}, partial=True)
            serializer.is_valid(raise_exception=True)

    def test_validate_is_active_no_instance(self):
        serializer = ServiceKeySerializer(instance=None, data={"is_active": True}, partial=False)
        with pytest.raises(ValidationError, match="Internal error"):
            serializer.is_valid(raise_exception=True)

    def test_validate_is_active_skip_if_field_unchanged(self, service_key_factory, service_cluster_eda):
        key1 = service_key_factory(service_cluster_eda)
        key1.is_active = True
        key1.save()
        serializer = ServiceKeySerializer(instance=key1, data={"is_active": True}, partial=True)

        with patch("aap_gateway_api.serializers.service_key.ServiceKey.objects.filter") as mock_filter:
            assert serializer.validate_is_active(True) is True

        mock_filter.assert_not_called()
