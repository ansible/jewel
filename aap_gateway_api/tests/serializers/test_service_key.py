from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.serializers.service_key import ServiceKeySerializerRead, ServiceKeySerializerWrite


@pytest.mark.django_db
class TestServiceKeySerializer:
    def test_meta_fields_include_service_key_fields(self):
        expected = ["service_cluster", "is_active", "algorithm", "secret_length", "mark_previous_inactive", "secret"]
        for field_name in expected:
            assert field_name in ServiceKeySerializerRead.Meta.fields

    def test_create_only_fields_are_read_only_and_deprecated(self):
        serializer = ServiceKeySerializerRead()

        assert serializer.fields["secret_length"].read_only
        assert serializer.fields["mark_previous_inactive"].read_only
        assert ServiceKeySerializerWrite._spectacular_annotation["deprecate_fields"] == [
            "service_cluster",
            "algorithm",
            "secret_length",
            "mark_previous_inactive",
            "secret",
        ]

    def test_validate_is_active(self, service_key_factory, service_cluster_eda):
        key1 = service_key_factory(service_cluster_eda)
        key2 = service_key_factory(service_cluster_eda)
        _ = service_key_factory(service_cluster_eda)
        key2.refresh_from_db()

        # At this point, key 3 is the only active key.

        with override_settings(MAX_ACTIVE_KEYS_PER_SERVICE=2):
            serializer = ServiceKeySerializerRead(instance=key1, data={"is_active": True}, partial=True)
            serializer.is_valid(raise_exception=True)

            key1.is_active = True
            key1.save()

            # We now have 2 active keys so trying to activate a third should fail
            serializer = ServiceKeySerializerRead(instance=key2, data={"is_active": True}, partial=True)
            with pytest.raises(ValidationError, match="Cannot activate this key"):
                serializer.is_valid(raise_exception=True)

        # Validate that increasing the setting now allows for key2 to be saved
        with override_settings(MAX_ACTIVE_KEYS_PER_SERVICE=3):
            serializer = ServiceKeySerializerRead(instance=key2, data={"is_active": True}, partial=True)
            serializer.is_valid(raise_exception=True)

    def test_validate_is_active_no_instance(self):
        serializer = ServiceKeySerializerRead(instance=None, data={"is_active": True}, partial=False)
        with pytest.raises(ValidationError, match="Internal error"):
            serializer.is_valid(raise_exception=True)

    def test_validate_is_active_skip_if_field_unchanged(self, service_key_factory, service_cluster_eda):
        key1 = service_key_factory(service_cluster_eda)
        key1.is_active = True
        key1.save()
        serializer = ServiceKeySerializerRead(instance=key1, data={"is_active": True}, partial=True)

        with patch("aap_gateway_api.serializers.service_key.ServiceKey.objects.filter") as mock_filter:
            assert serializer.validate_is_active(True) is True

        mock_filter.assert_not_called()

    def test_update_ignores_deprecated_create_only_fields(self, service_key_factory, service_cluster_eda, service_cluster_gateway):
        key = service_key_factory(service_cluster_eda)

        serializer = ServiceKeySerializerRead(
            instance=key,
            data={
                "is_active": False,
                "service_cluster": service_cluster_gateway.pk,
                "secret": "replacement-secret",
                "secret_length": 128,
                "mark_previous_inactive": True,
                "algorithm": "HS512",
            },
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        assert serializer.validated_data == {"is_active": False}
