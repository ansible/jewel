from unittest.mock import MagicMock, patch

import pytest
from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.utils import create_initial_data as seed_feature_flags
from django.conf import settings

from aap_gateway_api.models.http_port import HTTPPort, is_ipv6_enabled


@pytest.fixture
def feature_flag_setup():
    """
    Context manager fixture for feature flag setup and cleanup.
    Sets up feature flag, yields control to test, then restores original state.
    """
    from contextlib import contextmanager

    @contextmanager
    def _setup_flag(flag_name, flag_value):
        # Store original setting if it exists
        original_value = getattr(settings, flag_name, None)

        # Clean up and recreate feature flags
        AAPFlag.objects.filter(name=flag_name).delete()
        setattr(settings, flag_name, flag_value)
        seed_feature_flags()

        try:
            yield
        finally:
            # Restore original setting after test
            if original_value is not None:
                setattr(settings, flag_name, original_value)
            elif hasattr(settings, flag_name):
                delattr(settings, flag_name)
            # Re-seed with original value
            seed_feature_flags()

    return _setup_flag


class TestIsIPv6Enabled:
    """Unit tests for is_ipv6_enabled() function."""

    def test_ipv6_available_success(self):
        """Test that is_ipv6_enabled returns True when IPv6 socket can be created."""
        import socket as socket_module

        mock_socket = MagicMock()
        mock_socket_instance = MagicMock()
        mock_socket.return_value = mock_socket_instance

        with patch('aap_gateway_api.models.http_port.socket.socket', mock_socket):
            result = is_ipv6_enabled()

        assert result is True
        # Verify socket was called with correct arguments
        mock_socket.assert_called_once_with(socket_module.AF_INET6, socket_module.SOCK_STREAM)
        mock_socket_instance.close.assert_called_once()

    def test_ipv6_unavailable_oserror(self):
        """Test that is_ipv6_enabled returns False when OSError is raised."""
        mock_socket = MagicMock(side_effect=OSError("Address family not supported"))

        with patch('aap_gateway_api.models.http_port.socket.socket', mock_socket):
            result = is_ipv6_enabled()

        assert result is False
        mock_socket.assert_called_once()

    def test_ipv6_unavailable_socket_error(self):
        """Test that is_ipv6_enabled returns False when socket.error is raised."""
        import socket as socket_module

        mock_socket = MagicMock(side_effect=socket_module.error("Socket error"))

        with patch('aap_gateway_api.models.http_port.socket.socket', mock_socket):
            result = is_ipv6_enabled()

        assert result is False
        mock_socket.assert_called_once()

    def test_ipv6_unavailable_attribute_error(self):
        """Test that is_ipv6_enabled returns False when AttributeError is raised (AF_INET6 not available)."""
        # Simulate socket module not having AF_INET6 attribute
        import socket as socket_module

        mock_socket_instance = MagicMock()

        # Create a mock socket module that raises AttributeError when AF_INET6 is accessed
        class SocketModuleMock:
            SOCK_STREAM = socket_module.SOCK_STREAM

            def socket(self, *args, **kwargs):
                return mock_socket_instance

            def __getattr__(self, name):
                if name == 'AF_INET6':
                    raise AttributeError("module 'socket' has no attribute 'AF_INET6'")
                # For other attributes, try to get them from the real socket module
                return getattr(socket_module, name)

        mock_socket_module = SocketModuleMock()

        with patch('aap_gateway_api.models.http_port.socket', mock_socket_module):
            result = is_ipv6_enabled()

        assert result is False

    def test_ipv6_enabled_integration(self):
        """Integration test: verify is_ipv6_enabled works with actual socket module."""
        # This test uses the real socket module to verify the function works correctly
        # The result depends on whether the test environment supports IPv6
        result = is_ipv6_enabled()

        # Result should be a boolean
        assert isinstance(result, bool)
        # The function should not raise any exceptions
        assert result in (True, False)


class TestHTTPPortGetXdsListenerConfig:
    """Unit tests for HTTPPort.get_xds_listener_config() method."""

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "ipv6_enabled,expected_address,expected_ipv4_compat_present",
        [
            (True, "::", True),
            (False, "0.0.0.0", False),
        ],
    )
    def test_get_xds_listener_config_ipv6_default_and_fallback(self, ipv6_enabled, expected_address, expected_ipv4_compat_present):
        """Test that get_xds_listener_config defaults to IPv6 (::) when available, or falls back to IPv4 (0.0.0.0) when not."""
        # Create an HTTPPort instance
        http_port = HTTPPort.objects.create(name="test-port", number=8080, use_https=False)

        # Mock is_ipv6_enabled to return the test value
        with patch('aap_gateway_api.models.http_port.is_ipv6_enabled', return_value=ipv6_enabled):
            cfg = http_port.get_xds_listener_config()

        # Verify the address matches expected value
        assert cfg['address']['socket_address']['address'] == expected_address
        assert cfg['address']['socket_address']['port_value'] == 8080

        # Verify ipv4_compat presence matches expected value
        if expected_ipv4_compat_present:
            assert cfg['address']['socket_address']['ipv4_compat'] is True
        else:
            assert 'ipv4_compat' not in cfg['address']['socket_address']

    @pytest.mark.django_db
    @pytest.mark.parametrize("use_https,expected_transport_socket_present", [(True, True), (False, False)])
    def test_get_xds_listener_config_ipv6_with_https(self, use_https, expected_transport_socket_present):
        """Test that IPv6 default behavior works with both HTTP and HTTPS."""
        # Create an HTTPPort instance
        http_port = HTTPPort.objects.create(name="test-port", number=8443, use_https=use_https)

        # Mock is_ipv6_enabled to return True to verify IPv6 default behavior
        with patch('aap_gateway_api.models.http_port.is_ipv6_enabled', return_value=True):
            cfg = http_port.get_xds_listener_config()

        # Verify IPv6 is the default regardless of HTTPS setting
        assert cfg['address']['socket_address']['address'] == "::"
        assert cfg['address']['socket_address']['ipv4_compat'] is True

        # Verify HTTPS configuration is applied based on use_https setting
        assert ("transport_socket" in cfg["filter_chains"][0]) == expected_transport_socket_present
