"""Tests for ServiceOrchestrationMixin: load_types_and_permissions, _migrate_single_service."""

import uuid
from collections import OrderedDict
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    # Unmigrated query: no unmigrated resources remain
                    resp.json.return_value = {"count": 0, "results": []}
                else:
                    # Unfiltered registry query: resources exist (already migrated)
                    resp.json.return_value = {"count": 5, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
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
def test_migration_does_not_skip_when_registry_empty(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """When upstream registry is completely empty (not populated yet), migration should NOT be skipped."""

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
            # All queries return count=0 — registry is empty
            mock_client.list_resources.return_value.json.return_value = {
                "count": 0,
                "results": [],
            }
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        # Should NOT say "already synchronized"
        assert "already synchronized" not in captured.out
        # Should warn about empty registry
        assert "empty" in captured.err.lower() or "empty" in captured.out.lower()
        # Should attempt migration
        assert "Migrating data for" in captured.out


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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    resp.json.return_value = {
                        "count": 1,
                        "results": [{"name": "real-org", "ansible_id": "org-id"}],
                    }
                else:
                    resp.json.return_value = {"count": 0, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        with pytest.raises(CommandError):
            call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" not in captured.out
        assert "Migrating data for" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_skips_when_only_system_user_unmigrated(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """When the only unmigrated shared.user is the system user, treat it as synced."""

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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    resp.json.return_value = {
                        "count": 1,
                        "results": [{"name": settings.SYSTEM_USERNAME, "ansible_id": "sys-user-id", "resource_type": "shared.user"}],
                    }
                else:
                    resp.json.return_value = {"count": 10, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" in captured.out
        assert "skipping resource migration" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_proceeds_when_paginated_results_exceed_page(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """When count > len(results), more unmigrated resources exist on later pages — migration must proceed."""

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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    # Page has only the system user, but count indicates more on later pages
                    resp.json.return_value = {
                        "count": 3,
                        "results": [{"name": settings.SYSTEM_USERNAME, "ansible_id": "sys-user-id", "resource_type": "shared.user"}],
                    }
                elif "service_id" in filters:
                    resp.json.return_value = {"count": 10, "results": []}
                else:
                    resp.json.return_value = {"count": 0, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        with pytest.raises(CommandError):
            call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" not in captured.out
        assert "Migrating data for" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_proceeds_when_org_shares_system_username(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """An organization whose name matches SYSTEM_USERNAME must not be filtered out by the guard."""

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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    resp.json.return_value = {
                        "count": 1,
                        "results": [{"name": settings.SYSTEM_USERNAME, "ansible_id": "org-id", "resource_type": "shared.organization"}],
                    }
                elif "service_id" in filters:
                    resp.json.return_value = {"count": 10, "results": []}
                else:
                    resp.json.return_value = {"count": 0, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        with pytest.raises(CommandError):
            call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" not in captured.out
        assert "Migrating data for" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_guard_ignores_unsupported_resource_types(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Unmigrated resources of types NOT in resource_types_to_migrate do not block the guard.

    Simulates a registry where unsupported types (e.g. controller.jobtemplate)
    have unmigrated resources.  An unscoped unmigrated query would return
    count > 0, but the scoped query (content_type__resource_type__name__in)
    correctly returns 0 for migratable types only.
    """

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

            def list_resources_side_effect(filters=None):
                resp = Mock()
                filters = filters or {}
                if "is_partially_migrated" in filters:
                    # Scoped to migratable types: all migrated
                    resp.json.return_value = {"count": 0, "results": []}
                else:
                    # Unfiltered registry is populated (already migrated / unsupported types).
                    resp.json.return_value = {"count": 5, "results": []}
                return resp

            mock_client.list_resources.side_effect = list_resources_side_effect
            setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" in captured.out
        assert "skipping resource migration" in captured.out


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
            # 1st: scoped unmigrated query — finds resources to migrate
            responses = [Mock(json=Mock(return_value={"count": 1, "results": [{"name": "org1", "ansible_id": "o1"}]}))]
            # 2nd+: migration page fetches and remaining queries return 0
            responses += [Mock(json=Mock(return_value={"count": 0, "results": []}))] * 20
            mock_client.list_resources.side_effect = responses
            setup_empty_assignment_mocks(mock_client)
            created_clients.append(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        with pytest.raises((CommandError, KeyError)):
            call_command("migrate_service_data", username=admin_user.username)

        assert created_clients, "Expected GWResourceAPIClient to be instantiated"
        for mock_instance in created_clients:
            mock_instance.get_resource.assert_not_called()
            assert any(call.kwargs.get("filters", {}).get("extra_fields") == "resource_data" for call in mock_instance.list_resources.call_args_list), (
                "Expected list_resources to be called with extra_fields=resource_data"
            )

        captured = capsys.readouterr()
        assert "Migrating data for" in captured.out


@pytest.mark.django_db
def test_load_types_and_permissions_success(admin_user):
    """When all services respond 200 with no pagination, returns empty failure list."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    service_api = Mock()
    service_api.api_slug = "controller"

    mock_client = Mock()

    types_response = Mock()
    types_response.status_code = 200
    types_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_types.return_value = types_response

    perms_response = Mock()
    perms_response.status_code = 200
    perms_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_permissions.return_value = perms_response

    with patch(_ORCH_CLIENT, return_value=mock_client):
        failed = cmd.load_types_and_permissions([service_api], admin_user)

    assert failed == []
    mock_client.list_role_types.assert_called_once()
    mock_client.list_role_permissions.assert_called_once()


@pytest.mark.django_db
def test_load_types_and_permissions_partial_failure(admin_user, capsys):
    """When one service succeeds and another raises, only the failing slug is returned."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    good_service = Mock()
    good_service.api_slug = "controller"

    bad_service = Mock()
    bad_service.api_slug = "hub"

    good_client = Mock()
    types_resp = Mock()
    types_resp.status_code = 200
    types_resp.json.return_value = {"next": None, "results": []}
    good_client.list_role_types.return_value = types_resp
    perms_resp = Mock()
    perms_resp.status_code = 200
    perms_resp.json.return_value = {"next": None, "results": []}
    good_client.list_role_permissions.return_value = perms_resp

    bad_client = Mock()
    bad_client.list_role_types.side_effect = RuntimeError("connection refused")

    def client_factory(service_api, **kwargs):
        if service_api is good_service:
            return good_client
        return bad_client

    with patch(_ORCH_CLIENT, side_effect=client_factory):
        failed = cmd.load_types_and_permissions([good_service, bad_service], admin_user)

    assert "hub" in failed
    assert "controller" not in failed

    captured = capsys.readouterr()
    assert "Failed to load types and permissions from hub" in captured.err


@pytest.mark.django_db
def test_load_types_and_permissions_pagination_warning(admin_user, capsys):
    """When list_role_types returns a non-None next URL, a warning is logged."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    service_api = Mock()
    service_api.api_slug = "controller"

    mock_client = Mock()
    types_response = Mock()
    types_response.status_code = 200
    types_response.json.return_value = {"next": "http://service/api/v1/role_types/?page=2", "results": []}
    mock_client.list_role_types.return_value = types_response

    with patch(_ORCH_CLIENT, return_value=mock_client):
        failed = cmd.load_types_and_permissions([service_api], admin_user)

    assert "controller" in failed

    captured = capsys.readouterr()
    assert "has extra pages of types" in captured.err
    assert "Failed to load types and permissions from controller" in captured.err


@pytest.mark.django_db
@pytest.mark.parametrize(
    "types_status,types_next,perms_status,perms_next,expected_err",
    [
        pytest.param(503, None, 200, None, "role types gave 503", id="types_non_200"),
        pytest.param(200, None, 500, None, "permissions gave 500", id="perms_non_200"),
        pytest.param(200, None, 200, "http://service/?page=2", "has extra pages of types", id="perms_pagination"),
    ],
)
def test_load_types_and_permissions_error_scenarios(admin_user, capsys, types_status, types_next, perms_status, perms_next, expected_err):
    """Various error responses from role types/permissions APIs mark the service as failed."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    service_api = Mock()
    service_api.api_slug = "controller"

    mock_client = Mock()

    types_response = Mock()
    types_response.status_code = types_status
    types_response.data = "error"
    types_response.json.return_value = {"next": types_next, "results": []}
    mock_client.list_role_types.return_value = types_response

    perms_response = Mock()
    perms_response.status_code = perms_status
    perms_response.data = "error"
    perms_response.json.return_value = {"next": perms_next, "results": []}
    mock_client.list_role_permissions.return_value = perms_response

    with patch(_ORCH_CLIENT, return_value=mock_client):
        failed = cmd.load_types_and_permissions([service_api], admin_user)

    assert "controller" in failed
    captured = capsys.readouterr()
    assert expected_err in captured.err
