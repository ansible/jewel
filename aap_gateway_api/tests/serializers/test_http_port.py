from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from aap_gateway_api.models import HTTPPort
from aap_gateway_api.serializers.http_port import HTTPPortSerializer


@pytest.mark.django_db
class TestHTTPPortSerializer:
    """Tests for HTTPPortSerializer."""

    @pytest.mark.parametrize(
        "instance_value,new_value,should_raise,description",
        [
            (True, True, False, "allows True to True"),
            (False, False, False, "allows False to False"),
            (False, True, False, "allows False to True"),
            (True, False, True, "prevents True to False"),
            (None, True, False, "allows True on new instance"),
            (None, False, False, "allows False on new instance"),
        ],
    )
    def test_validate_is_api_port(self, instance_value, new_value, should_raise, description):
        """Test is_api_port validation with various transitions."""
        # Create instance if needed
        if instance_value is not None:
            port = HTTPPort.objects.create(
                name=f"Port {instance_value}",
                number=443 if instance_value else 9021,
                use_https=instance_value,
                is_api_port=instance_value,
            )
            serializer = HTTPPortSerializer(instance=port)
        else:
            serializer = HTTPPortSerializer()

        if should_raise:
            with pytest.raises(ValidationError) as exc_info:
                serializer.validate_is_api_port(new_value)
            assert 'cannot be changed to a non-api port' in str(exc_info.value.detail[0]).lower()
        else:
            result = serializer.validate_is_api_port(new_value)
            assert result == new_value

    def test_serializer_meta_fields_includes_all_http_port_fields(self):
        """Test that serializer Meta.fields includes all necessary fields."""
        assert 'number' in HTTPPortSerializer.Meta.fields
        assert 'use_https' in HTTPPortSerializer.Meta.fields
        assert 'is_api_port' in HTTPPortSerializer.Meta.fields
        # Also check for inherited fields
        assert 'name' in HTTPPortSerializer.Meta.fields

    def test_create_http_port_via_serializer(self):
        """Test creating an HTTP port through the serializer."""
        data = {
            'name': 'Test API Port',
            'number': 8443,
            'use_https': True,
            'is_api_port': True,
        }
        mock_request = Mock(query_params={})
        serializer = HTTPPortSerializer(data=data, context={'request': mock_request})
        assert serializer.is_valid(), serializer.errors
        port = serializer.save()
        assert port.name == 'Test API Port'
        assert port.number == 8443
        assert port.use_https is True
        assert port.is_api_port is True

    def test_update_http_port_via_serializer(self):
        """Test updating an HTTP port through the serializer (except is_api_port to False)."""
        port = HTTPPort.objects.create(name="Original", number=443, use_https=True, is_api_port=False)

        data = {
            'name': 'Updated Port',
            'number': 8443,
        }
        mock_request = Mock(query_params={})
        serializer = HTTPPortSerializer(instance=port, data=data, partial=True, context={'request': mock_request})
        assert serializer.is_valid(), serializer.errors
        updated_port = serializer.save()
        assert updated_port.name == 'Updated Port'
        assert updated_port.number == 8443

    def test_update_api_port_to_non_api_fails(self):
        """Test that updating an API port to non-API port fails validation."""
        port = HTTPPort.objects.create(name="API Port", number=443, use_https=True, is_api_port=True)

        data = {'is_api_port': False}
        serializer = HTTPPortSerializer(instance=port, data=data, partial=True)
        assert not serializer.is_valid()
        assert 'is_api_port' in serializer.errors
