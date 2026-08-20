from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.serializers.service_auth import ServiceKeySerializer


@pytest.mark.django_db
class TestServiceKeySerializer:
    def test_create_delegates_to_generate_key(self, service_cluster_eda):
        factory = APIRequestFactory()
        request = factory.post("/")
        serializer = ServiceKeySerializer(context={"request": request})

        validated_data = {
            "service_cluster": service_cluster_eda,
            "mark_previous_inactive": True,
            "secret_length": 64,
            "algorithm": "HS256",
        }

        with patch.object(service_cluster_eda, "generate_key", wraps=service_cluster_eda.generate_key) as mock_gen:
            obj = serializer.create(validated_data)
            mock_gen.assert_called_once_with(
                name=None,
                algorithm="HS256",
                secret_length=64,
                mark_previous_inactive=True,
            )
        assert isinstance(obj, ServiceKey)

    def test_create_passes_name(self, service_cluster_eda):
        factory = APIRequestFactory()
        request = factory.post("/")
        serializer = ServiceKeySerializer(context={"request": request})

        validated_data = {
            "service_cluster": service_cluster_eda,
            "mark_previous_inactive": False,
            "secret_length": 128,
            "algorithm": "HS512",
            "name": "my-custom-key",
        }

        obj = serializer.create(validated_data)
        assert obj.name == "my-custom-key"
        assert obj.algorithm == "HS512"

    def test_secret_length_field_bounds(self):
        serializer = ServiceKeySerializer()
        field = serializer.fields["secret_length"]
        assert field.min_value == 64
        assert field.max_value == 512
        assert field.default == 64
        assert field.write_only is True

    def test_mark_previous_inactive_is_required(self):
        serializer = ServiceKeySerializer()
        field = serializer.fields["mark_previous_inactive"]
        assert field.required is True
        assert field.write_only is True

    def test_algorithm_default(self):
        serializer = ServiceKeySerializer()
        field = serializer.fields["algorithm"]
        assert field.default == ServiceKey.JWTAlgorithm.HS256

    def test_meta_fields_include_service_key_fields(self):
        expected = ["service_cluster", "is_active", "algorithm", "secret_length", "mark_previous_inactive", "secret"]
        for field_name in expected:
            assert field_name in ServiceKeySerializer.Meta.fields
