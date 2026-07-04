"""Tests for ServiceOrchestrationMixin: load_types_and_permissions, _migrate_single_service."""

import uuid
from collections import OrderedDict
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import SEP_CHAR, assert_all_resources_synced, setup_empty_assignment_mocks

_ORCH_CLIENT = "aap_gateway_api.management.commands._migrate_service_data.service_orchestration.resources_client.GWResourceAPIClient"


@pytest.mark.django_db
def test_migrate_single_service_skips_unknown_service_type(admin_user, capsys, service_api_route_controller):
    """When service metadata reports an unknown service_type, the service is skipped."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}
    cmd.resource_types_to_migrate = OrderedDict()

    mock_client = Mock()
    mock_client.service = service_api_route_controller
    mock_client.user = admin_user
    mock_client.get_service_metadata.return_value.json.return_value = {
        "service_id": str(uuid.uuid4()),
        "service_type": "nonexistent_type",
    }

    with patch(_ORCH_CLIENT, return_value=mock_client):
        success, error = cmd._migrate_single_service(service_api_route_controller, service_api_route_controller.api_slug, admin_user)

    assert success is False
    captured = capsys.readouterr()
    assert "Skipping service" in captured.err
    assert "Migrations are not allowed" in captured.err


@pytest.mark.django_db
def test_migrate_single_service_skips_mismatched_service_type(admin_user, capsys, service_api_route_controller):
    """When the reported service_type doesn't match the configured one, the service is skipped."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}
    cmd.resource_types_to_migrate = OrderedDict()

    mock_client = Mock()
    mock_client.service = service_api_route_controller
    mock_client.user = admin_user
    mock_client.get_service_metadata.return_value.json.return_value = {
        "service_id": str(uuid.uuid4()),
        "service_type": "hub",
    }

    with patch(_ORCH_CLIENT, return_value=mock_client):
        success, error = cmd._migrate_single_service(service_api_route_controller, service_api_route_controller.api_slug, admin_user)

    assert success is False
    captured = capsys.readouterr()
    assert "Skipping service" in captured.err
    assert "Service type mismatch" in captured.err


@pytest.mark.django_db(transaction=True)
def test_migrate_with_ignored_flags(
    migration_service,
    admin_user,
    admin_api_client,
    conflicting_org,
    conflicting_team,
    patched_resource_client,
    patched_load_rbac,
    capsys,
):
    """Test that deprecated flags are ignored with warnings and migration still works"""
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data",
        api_slug=migration_service.api_slug,
        username=admin_user.username,
        merge_teams=False,
        merge_organizations=False,
    )

    assert_all_resources_synced(admin_api_client, migration_service, service_client)

    captured = capsys.readouterr()
    assert "Warning: --api-slug flag is ignored" in captured.err
    assert "Warning: --merge-teams flag is ignored" in captured.err
    assert "Warning: --merge-organizations flag is ignored" in captured.err

    from aap_gateway_api.models import Organization

    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    original_org_teams = list(conflicting_org.teams.all().values_list("name", flat=True))
    assert original_org_teams == [conflicting_team.name]


@pytest.mark.django_db(transaction=True)
def test_migrate_forced_merge_behavior(
    migration_service,
    admin_user,
    admin_api_client,
    conflicting_org,
    conflicting_team,
    patched_resource_client,
    patched_load_rbac,
):
    """Test that merge flags are ignored and behavior is always merge=True"""
    from aap_gateway_api.models import Organization, Team

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data",
        username=admin_user.username,
        merge_teams=False,
        merge_organizations=False,
    )

    assert_all_resources_synced(admin_api_client, migration_service, service_client)

    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(
        organization=conflicting_org,
        name=migration_service.api_slug + SEP_CHAR + conflicting_team.name,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_migrate_default_merge_behavior(
    migration_service,
    admin_user,
    admin_api_client,
    conflicting_org,
    conflicting_team,
    patched_resource_client,
    patched_load_rbac,
):
    """Test default merge behavior with no flags specified"""
    from aap_gateway_api.models import Organization, Team

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)

    assert_all_resources_synced(admin_api_client, migration_service, service_client)

    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(
        organization=conflicting_org,
        name=migration_service.api_slug + SEP_CHAR + conflicting_team.name,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_migration_skips_when_already_synced(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test that migration short-circuits when all resources are already migrated."""

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):

        def mock_client_factory(service_api, *args, **kwargs):
            mock_client = Mock()
            mock_client.service = service_api
            mock_client.user = admin_user
            mock_client.get_service_metadata.return_value.json.return_value = {
                "service_id": str(uuid.uuid4()),
                "service_type": "controller",
            }
            mock_client.list_resources.return_value.json.return_value = {
                "count": 0,
                "results": [],
            }
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" in captured.out
        assert "skipping resource migration" in captured.out
        assert "Migrating data for" not in captured.out
        assert "role assignments" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_proceeds_when_not_synced(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test that migration proceeds normally when unmigrated resources exist."""

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):

        def mock_client_factory(service_api, *args, **kwargs):
            mock_client = Mock()
            mock_client.service = service_api
            mock_client.user = admin_user
            mock_client.get_service_metadata.return_value.json.return_value = {
                "service_id": str(uuid.uuid4()),
                "service_type": "controller",
            }
            mock_client.list_resources.return_value.json.return_value = {
                "count": 1,
                "results": [],
            }
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" not in captured.out
        assert "Migrating data for" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_uses_bulk_fetch(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test that migration uses list_resources with extra_fields instead of individual calls."""

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        created_clients = []

        def mock_client_factory(service_api, *args, **kwargs):
            mock_client = Mock()
            mock_client.service = service_api
            mock_client.user = admin_user
            mock_client.get_service_metadata.return_value.json.return_value = {
                "service_id": str(uuid.uuid4()),
                "service_type": "controller",
            }
            responses = [Mock(json=Mock(return_value={"count": 1, "results": []}))]
            responses += [Mock(json=Mock(return_value={"count": 0, "results": []}))] * 20
            mock_client.list_resources.side_effect = responses
            setup_empty_assignment_mocks(mock_client)
            created_clients.append(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        assert created_clients, "Expected GWResourceAPIClient to be instantiated"
        for mock_instance in created_clients:
            mock_instance.get_resource.assert_not_called()
            assert any(call.kwargs.get("filters", {}).get("extra_fields") == "resource_data" for call in mock_instance.list_resources.call_args_list), (
                "Expected list_resources to be called with extra_fields=resource_data"
            )

        captured = capsys.readouterr()
        assert "Migration Summary" in captured.out
        assert "Migrating data for" in captured.out
