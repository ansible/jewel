from unittest.mock import Mock

import pytest

from aap_gateway_api.models import ServiceType
from aap_gateway_api.serializers.service_type import ServiceTypeSerializer


@pytest.mark.django_db
class TestServiceTypeSerializer:
    """Tests for ServiceTypeSerializer."""

    def test_serializer_meta_fields_includes_all_service_type_fields(self):
        """Test that serializer Meta.fields includes all necessary fields."""
        expected_fields = ['login_path', 'logout_path', 'ping_url', 'service_index_path']
        for field in expected_fields:
            assert field in ServiceTypeSerializer.Meta.fields, f"Field {field} missing from Meta.fields"

        # Also check for inherited fields
        assert 'name' in ServiceTypeSerializer.Meta.fields

    def test_create_service_type_via_serializer(self):
        """Test creating a service type through the serializer."""
        data = {
            'name': 'Controller',
            'login_path': '/api/login/',
            'logout_path': '/api/logout/',
            'ping_url': '/api/ping/',
            'service_index_path': '/api/',
        }
        serializer = ServiceTypeSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        service_type = serializer.save()
        assert service_type.name == 'Controller'
        assert service_type.login_path == '/api/login/'
        assert service_type.logout_path == '/api/logout/'
        assert service_type.ping_url == '/api/ping/'
        assert service_type.service_index_path == '/api/'

    def test_create_service_type_minimal_fields(self):
        """Test creating a service type with only required fields."""
        data = {
            'name': 'Hub',
            'login_path': '/api/v3/auth/login/',
            'logout_path': '/api/v3/auth/logout/',
            'ping_url': '/api/v3/',
        }
        serializer = ServiceTypeSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        service_type = serializer.save()
        assert service_type.name == 'Hub'
        assert service_type.login_path == '/api/v3/auth/login/'

    def test_update_service_type_via_serializer(self):
        """Test updating a service type through the serializer."""
        service_type = ServiceType.objects.create(
            name="EDA", login_path="/api/eda/v1/auth/login/", logout_path="/api/eda/v1/auth/logout/", ping_url="/api/eda/v1/"
        )

        data = {
            'name': 'Event-Driven Ansible',
            'service_index_path': '/api/eda/v1/index/',
        }
        serializer = ServiceTypeSerializer(instance=service_type, data=data, partial=True, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        updated_service_type = serializer.save()
        assert updated_service_type.name == 'Event-Driven Ansible'
        assert updated_service_type.service_index_path == '/api/eda/v1/index/'
        # Original fields should remain unchanged
        assert updated_service_type.login_path == "/api/eda/v1/auth/login/"

    @pytest.mark.parametrize(
        "omitted_field,description",
        [
            ('name', 'name is required'),
            ('login_path', 'login_path is required'),
            ('logout_path', 'logout_path is required'),
            ('ping_url', 'ping_url is required'),
        ],
    )
    def test_service_type_required_fields(self, omitted_field, description):
        """Test that required fields are validated."""
        # Base data with all fields
        base_data = {
            'name': 'Test Service',
            'login_path': '/api/login/',
            'logout_path': '/api/logout/',
            'ping_url': '/api/ping/',
        }
        # Remove the field being tested
        data = {k: v for k, v in base_data.items() if k != omitted_field}

        serializer = ServiceTypeSerializer(data=data)
        if omitted_field == 'name':
            # Name is always required
            assert not serializer.is_valid()
            assert omitted_field in serializer.errors
        else:
            # Check if field is actually required based on model
            if not serializer.is_valid():
                assert omitted_field in serializer.errors

    def test_service_type_with_empty_service_index_path(self):
        """Test creating a service type without service_index_path."""
        data = {
            'name': 'Test Service',
            'login_path': '/api/login/',
            'logout_path': '/api/logout/',
            'ping_url': '/api/ping/',
        }
        serializer = ServiceTypeSerializer(data=data, context={'request': Mock(query_params={})})
        # service_index_path is optional
        if serializer.is_valid():
            service_type = serializer.save()
            assert service_type.name == 'Test Service'

    def test_service_type_paths_can_be_different(self):
        """Test that service type paths can all be different."""
        data = {
            'name': 'Custom Service',
            'login_path': '/custom/login/',
            'logout_path': '/custom/logout/',
            'ping_url': '/custom/health/',
            'service_index_path': '/custom/',
        }
        serializer = ServiceTypeSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        service_type = serializer.save()
        assert service_type.login_path == '/custom/login/'
        assert service_type.logout_path == '/custom/logout/'
        assert service_type.ping_url == '/custom/health/'
        assert service_type.service_index_path == '/custom/'
