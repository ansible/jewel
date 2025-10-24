from unittest.mock import Mock

import pytest

from aap_gateway_api.models import ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.serializers.service_node import ServiceNodeSerializer


@pytest.mark.django_db
class TestServiceNodeSerializer:
    """Tests for ServiceNodeSerializer."""

    @pytest.fixture
    def service_cluster(self):
        """Create a service cluster for testing."""
        service_type = ServiceType.objects.create(name="Controller", login_path="/api/login/", logout_path="/api/logout/", ping_url="/api/ping/")
        return ServiceCluster.objects.create(name="Test Cluster", service_type=service_type, auth_type="shared_secret")

    @pytest.mark.parametrize(
        "input_value,expected_behavior,description",
        [
            ("tag1, tag2, tag3", "contains_all", "normalizes comma-separated list"),
            ("tag1, tag2, tag1, tag3", "unique_only", "removes duplicates"),
            ("", "empty_or_none", "handles empty string"),
            (None, "empty_or_none", "handles None"),
        ],
    )
    def test_validate_tags(self, service_cluster, input_value, expected_behavior, description):
        """Test tags field validation and normalization."""
        serializer = ServiceNodeSerializer()
        result = serializer.validate_tags(input_value)

        if expected_behavior == "contains_all":
            assert "tag1" in result
            assert "tag2" in result
            assert "tag3" in result
        elif expected_behavior == "unique_only":
            tags = set(result.split(','))
            assert len(tags) == 3
            assert tags == {"tag1", "tag2", "tag3"}
        elif expected_behavior == "empty_or_none":
            assert result is None or result == ""

    def test_serializer_meta_fields_includes_all_node_fields(self):
        """Test that serializer Meta.fields includes all necessary fields."""
        assert 'address' in ServiceNodeSerializer.Meta.fields
        assert 'service_cluster' in ServiceNodeSerializer.Meta.fields
        assert 'tags' in ServiceNodeSerializer.Meta.fields
        # Also check for inherited fields
        assert 'name' in ServiceNodeSerializer.Meta.fields

    def test_create_service_node_via_serializer(self, service_cluster):
        """Test creating a service node through the serializer."""
        data = {
            'name': 'Test Node 1',
            'address': '192.168.1.10',
            'service_cluster': service_cluster.id,
            'tags': 'production,primary',
        }
        mock_request = Mock(query_params={})
        serializer = ServiceNodeSerializer(data=data, context={'request': mock_request})
        assert serializer.is_valid(), serializer.errors
        node = serializer.save()
        assert node.name == 'Test Node 1'
        assert node.address == '192.168.1.10'
        assert 'production' in node.tags
        assert 'primary' in node.tags

    def test_create_service_node_without_tags(self, service_cluster):
        """Test creating a service node without tags."""
        data = {
            'name': 'Test Node 2',
            'address': '192.168.1.20',
            'service_cluster': service_cluster.id,
        }
        mock_request = Mock(query_params={})
        serializer = ServiceNodeSerializer(data=data, context={'request': mock_request})
        assert serializer.is_valid(), serializer.errors
        node = serializer.save()
        assert node.name == 'Test Node 2'
        assert node.address == '192.168.1.20'

    def test_update_service_node_tags(self, service_cluster):
        """Test updating service node tags."""
        node = ServiceNode.objects.create(name="Node 1", address="192.168.1.10", service_cluster=service_cluster, tags="old,tags")

        data = {'tags': 'new, tags, updated'}
        mock_request = Mock(query_params={})
        serializer = ServiceNodeSerializer(instance=node, data=data, partial=True, context={'request': mock_request})
        assert serializer.is_valid(), serializer.errors
        updated_node = serializer.save()
        tags = set(updated_node.tags.split(','))
        assert 'new' in tags
        assert 'tags' in tags
        assert 'updated' in tags
        assert 'old' not in tags

    @pytest.mark.parametrize(
        "omitted_field,base_data_func,description",
        [
            ('address', lambda sc: {'name': 'Test Node', 'service_cluster': sc.id}, 'address is required'),
            ('service_cluster', lambda sc: {'name': 'Test Node', 'address': '192.168.1.10'}, 'service_cluster is required'),
        ],
    )
    def test_service_node_required_fields(self, service_cluster, omitted_field, base_data_func, description):
        """Test that required fields are validated."""
        data = base_data_func(service_cluster)
        serializer = ServiceNodeSerializer(data=data)
        assert not serializer.is_valid()
        assert omitted_field in serializer.errors
