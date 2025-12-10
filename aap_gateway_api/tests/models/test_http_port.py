from unittest.mock import MagicMock, patch

import pytest

from aap_gateway_api.models.http_port import is_ipv6_enabled


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_value,expected_result",
    [
        ('True', '::'),
        ('False', '0.0.0.0'),
    ],
)
def test_ipv6_flag_on_xds_listener_config(flag_value, expected_result, http_port, settings_override_mutable, settings):
    with settings_override_mutable('FLAGS'):
        settings.FLAGS['FEATURE_GATEWAY_IPV6_USAGE_ENABLED'][0]['value'] = flag_value
        config = http_port.get_xds_listener_config()
        assert config['address']['socket_address']['address'] == expected_result


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
