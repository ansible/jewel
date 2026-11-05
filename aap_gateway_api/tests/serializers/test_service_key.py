import pytest

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
