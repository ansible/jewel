from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.django_db
@patch('envoy.service.auth.v3.external_auth_pb2_grpc.add_AuthorizationServicer_to_server')
@patch('grpc.server')
def test_run_server_setup_observability(mock_server_factory, mock_add_servicer):
    """Test that _run_server calls setup_observability."""
    from ansible_base.observability import setup_observability

    from aap_gateway_api.management.commands.start_grpc_server import _run_server

    # Reset mock from conftest to track calls in this test
    setup_observability.reset_mock()

    # Mock gRPC server
    mock_grpc_server = MagicMock()
    mock_server_factory.return_value = mock_grpc_server
    mock_grpc_server.wait_for_termination.side_effect = KeyboardInterrupt()

    try:
        _run_server(bind_address="[::]:50051", debug=False)
    except KeyboardInterrupt:
        pass

    # Verify setup_observability was called
    setup_observability.assert_called_once_with(service_name="gateway-grpc")


@pytest.mark.django_db
@patch('envoy.service.auth.v3.external_auth_pb2_grpc.add_AuthorizationServicer_to_server')
@patch('grpc.server')
def test_run_server_debug_mode(mock_server_factory, mock_add_servicer):
    """Test that _run_server handles debug mode correctly."""
    from aap_gateway_api.management.commands.start_grpc_server import _run_server

    mock_grpc_server = MagicMock()
    mock_server_factory.return_value = mock_grpc_server
    mock_grpc_server.wait_for_termination.side_effect = KeyboardInterrupt()

    # Mock debugpy in sys.modules before it's imported
    mock_debugpy = MagicMock()
    with patch.dict('sys.modules', {'debugpy': mock_debugpy}):
        try:
            _run_server(bind_address="[::]:50051", debug=True)
        except KeyboardInterrupt:
            pass

        # Verify debugpy.listen was called in debug mode
        mock_debugpy.listen.assert_called_once_with(("0.0.0.0", 3001))
