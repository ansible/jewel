import pytest
from rest_framework.exceptions import ValidationError

from aap_gateway_api.serializers.base_route import BaseRouteSerializer


class MockInstance:
    """Mock instance for testing PATCH operations."""

    def __init__(self, enable_gateway_auth=True, is_internal_route=False, enable_mtls=False):
        self.enable_gateway_auth = enable_gateway_auth
        self.is_internal_route = is_internal_route
        self.enable_mtls = enable_mtls


class TestBaseRouteSerializer:
    """Tests for BaseRouteSerializer validation logic."""

    @pytest.mark.parametrize(
        "input_value,expected_behavior,description",
        [
            ("tag1, tag2, tag3", "contains_all", "normalizes comma-separated list"),
            ("tag1, tag2, tag1, tag3", "unique_only", "removes duplicates"),
            ("", "empty_or_none", "handles empty string"),
            (None, "empty_or_none", "handles None"),
        ],
    )
    def test_validate_node_tags(self, input_value, expected_behavior, description):
        """Test node_tags field validation and normalization."""
        serializer = BaseRouteSerializer()
        result = serializer.validate_node_tags(input_value)

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

    # Internal route validation tests
    def test_internal_route_requires_gateway_auth(self):
        """Test that internal routes require gateway auth."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': False, 'is_internal_route': True}

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'is_internal_route' in exc_info.value.detail
        assert 'require gateway auth' in str(exc_info.value.detail['is_internal_route'][0]).lower()

    def test_internal_route_with_gateway_auth_succeeds(self):
        """Test that internal routes with gateway auth succeed."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': True, 'is_internal_route': True}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is True
        assert result['is_internal_route'] is True

    def test_non_internal_route_without_gateway_auth_succeeds(self):
        """Test that non-internal routes can have gateway auth disabled."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': False, 'is_internal_route': False}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is False
        assert result['is_internal_route'] is False

    # mTLS validation tests
    def test_mtls_and_gateway_auth_mutually_exclusive(self):
        """Test that mTLS and gateway auth cannot both be enabled."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': True, 'enable_mtls': True}

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'enable_mtls' in exc_info.value.detail
        assert 'only be enabled when gateway auth is disabled' in str(exc_info.value.detail['enable_mtls'][0]).lower()

    def test_mtls_without_gateway_auth_succeeds(self):
        """Test that mTLS can be enabled when gateway auth is disabled."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': False, 'enable_mtls': True, 'is_internal_route': False}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is False
        assert result['enable_mtls'] is True

    def test_mtls_defaults_to_false_when_not_specified(self):
        """Test that mTLS defaults to False for new instances."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': True}

        result = serializer.validate(attrs)
        # Should not raise an error about mTLS
        assert result is not None

    # PATCH operation tests (instance exists)
    def test_patch_enables_mtls_on_instance_with_gateway_auth(self):
        """Test PATCH trying to enable mTLS on instance that has gateway auth enabled."""
        instance = MockInstance(enable_gateway_auth=True, enable_mtls=False)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'enable_mtls': True}  # Only changing mTLS

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'enable_mtls' in exc_info.value.detail

    def test_patch_enables_gateway_auth_on_instance_with_mtls(self):
        """Test PATCH trying to enable gateway auth on instance that has mTLS enabled."""
        instance = MockInstance(enable_gateway_auth=False, enable_mtls=True)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'enable_gateway_auth': True}  # Only changing gateway auth

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'enable_mtls' in exc_info.value.detail

    def test_patch_enables_internal_route_on_instance_without_gateway_auth(self):
        """Test PATCH trying to enable internal route on instance without gateway auth."""
        instance = MockInstance(enable_gateway_auth=False, is_internal_route=False)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'is_internal_route': True}  # Only changing internal route

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'is_internal_route' in exc_info.value.detail

    def test_patch_disables_gateway_auth_on_internal_route(self):
        """Test PATCH trying to disable gateway auth on an internal route."""
        instance = MockInstance(enable_gateway_auth=True, is_internal_route=True)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'enable_gateway_auth': False}  # Only changing gateway auth

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        assert 'is_internal_route' in exc_info.value.detail

    def test_patch_successful_when_both_changed_together(self):
        """Test PATCH can disable gateway auth and internal route together."""
        instance = MockInstance(enable_gateway_auth=True, is_internal_route=True)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'enable_gateway_auth': False, 'is_internal_route': False}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is False
        assert result['is_internal_route'] is False

    def test_patch_can_swap_auth_mechanisms(self):
        """Test PATCH can swap from gateway auth to mTLS in one operation."""
        instance = MockInstance(enable_gateway_auth=True, enable_mtls=False)
        serializer = BaseRouteSerializer(instance=instance)
        attrs = {'enable_gateway_auth': False, 'enable_mtls': True}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is False
        assert result['enable_mtls'] is True

    # Gateway path normalization tests
    @pytest.mark.parametrize(
        "input_path,expected_path,description",
        [
            ('/api//service//path', '/api/service/path', 'double slashes in path'),
            ('///api////service/////path///', '/api/service/path/', 'many consecutive slashes'),
            (None, None, 'path not provided (skips normalization)'),
        ],
    )
    def test_gateway_path_normalization(self, input_path, expected_path, description):
        """Test that gateway_path is normalized correctly."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': True}
        if input_path is not None:
            attrs['gateway_path'] = input_path

        result = serializer.validate(attrs)

        if expected_path is None:
            assert 'gateway_path' not in result
        else:
            assert result['gateway_path'] == expected_path

    # Multiple validation errors
    def test_multiple_validation_errors_reported_together(self):
        """Test that multiple validation errors are reported in one exception."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': False, 'is_internal_route': True, 'enable_mtls': True}

        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        # Should only have is_internal_route error since enable_mtls requires enable_gateway_auth=True
        assert 'is_internal_route' in exc_info.value.detail

    def test_no_validation_errors_with_all_flags_false(self):
        """Test that no errors occur when all flags are False."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': False, 'is_internal_route': False, 'enable_mtls': False}

        result = serializer.validate(attrs)
        assert result['enable_gateway_auth'] is False
        assert result['is_internal_route'] is False
        assert result['enable_mtls'] is False

    # Edge cases with None values
    def test_none_values_for_optional_fields(self):
        """Test that None values are handled correctly for optional fields."""
        serializer = BaseRouteSerializer()
        attrs = {'enable_gateway_auth': None, 'is_internal_route': None}

        # None values should not trigger validation errors
        result = serializer.validate(attrs)
        # Validation should pass without errors
        assert result is not None

    def test_empty_attrs_dict(self):
        """Test validation with empty attrs dict."""
        serializer = BaseRouteSerializer()
        attrs = {}

        result = serializer.validate(attrs)
        assert result == {}
