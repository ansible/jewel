"""Tests for Command class itself: handle, _process_all_services, _report_migration_summary,
add_arguments, _warn_ignored_flags.

These tests mock the mixin methods and focus on the command orchestration logic.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import setup_basic_service_client_mocks, setup_empty_assignment_mocks


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


def test_warn_ignored_flags_only_when_present(capsys):
    """Test that _warn_ignored_flags only emits warnings for flags actually present in options."""
    cmd = MigrateCommand()

    cmd._warn_ignored_flags({"api_slug": "test-slug", "merge_teams": True, "merge_organizations": True})
    captured = capsys.readouterr()
    assert "Warning: --api-slug flag is ignored" in captured.err
    assert "Warning: --merge-teams flag is ignored" in captured.err
    assert "Warning: --merge-organizations flag is ignored" in captured.err

    cmd._warn_ignored_flags({})
    captured = capsys.readouterr()
    assert "Warning:" not in captured.err


@pytest.mark.django_db(transaction=True)
def test_service_processing_order(
    admin_user,
    capsys,
    service_api_route_controller,
    service_api_route_hub,
    service_api_route_eda,
    patched_resource_client,
):
    """Test that services are processed in exact order: controller, hub, eda"""

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_client = Mock()
        mock_client.get_service_metadata.side_effect = Exception("Test order tracking")
        mock_client_class.return_value = mock_client

        with pytest.raises(CommandError):
            call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        output_lines = captured.out.split('\n')

        processing_lines = [line for line in output_lines if "Processing service:" in line]

        assert len(processing_lines) == 3, output_lines
        assert service_api_route_controller.service_cluster.service_type.name == "controller"
        assert service_api_route_hub.service_cluster.service_type.name == "hub"
        assert service_api_route_eda.service_cluster.service_type.name == "eda"

        assert service_api_route_controller.api_slug in processing_lines[0]
        assert service_api_route_hub.api_slug in processing_lines[1]
        assert service_api_route_eda.api_slug in processing_lines[2]


@pytest.mark.django_db(transaction=True)
def test_migration_error_handling_and_summary(
    admin_user,
    capsys,
    service_api_route_controller,
    service_api_route_hub,
    patched_resource_client,
    system_user,
):
    """Test error handling and migration summary for mixed success/failure scenarios"""

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        from requests.exceptions import HTTPError

        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'

        def mock_client_factory(service_api, *args, **kwargs):
            mock_client = Mock()
            mock_client.service = service_api
            mock_client.user = admin_user

            if service_api.service_cluster.service_type.name == "controller":
                mock_client.get_service_metadata.return_value.json.return_value = {
                    "service_id": str(uuid.uuid4()),
                    "service_type": "controller",
                }
                mock_client.list_resources.return_value.json.return_value = {
                    "count": 0,
                    "results": [],
                }
                setup_empty_assignment_mocks(mock_client)
            else:
                mock_client.get_service_metadata.side_effect = HTTPError("Mock HTTP error")
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        with pytest.raises(CommandError) as exc_info:
            call_command("migrate_service_data", username=admin_user.username)

        error_message = str(exc_info.value)
        assert "Migration failed" in error_message
        assert service_api_route_hub.api_slug in error_message

        captured = capsys.readouterr()
        assert "=== Migration Summary ===" in captured.out
        assert "Successful migrations: 1" in captured.out
        assert "Failed migrations: 1" in captured.out
        assert "Failed to migrate the following services:" in captured.err
        assert service_api_route_hub.api_slug in captured.err


@pytest.mark.django_db(transaction=True)
def test_single_service_migration(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test migration with only a single service available"""

    service_api_route_controller.api_slug = "test-controller-slug"
    service_api_route_controller.gateway_path = "/api/test-controller-slug/"
    service_api_route_controller.save()

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None

        mock_client = Mock()
        setup_basic_service_client_mocks(mock_client, service_api_route_controller, admin_user)

        mock_client.list_resources.return_value.json.return_value = {
            "count": 0,
            "results": [],
        }
        mock_client_class.return_value = mock_client

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "Found 1 services to migrate" in captured.out
        assert f"Processing service: {service_api_route_controller.api_slug}" in captured.out
        assert "Successful migrations: 1" in captured.out
        assert "Failed migrations: 0" in captured.out
        assert "All services migration completed successfully!" in captured.out

        assert "hub" not in captured.out
        assert "eda" not in captured.out


@pytest.mark.django_db(transaction=True)
def test_no_services_found_error(admin_user):
    """Test error when no DefaultServiceType services are found"""
    with pytest.raises(CommandError) as exc_info:
        call_command("migrate_service_data", username=admin_user.username)

    assert "No services found with expected service types" in str(exc_info.value)
