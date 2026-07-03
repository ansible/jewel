"""Tests for SuperuserSyncMixin: _ensure_controller_gateway_superusers, _collect_controller_superusers,
_demote_extra_superusers, _get_gateway_user, _sync_controller_superuser, _sync_hub_eda_superuser,
and the multi-service migration integration test.
"""

from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import User
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import kill_test_service, launch_test_service


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


def _assert_gateway_user_superuser_status(username, expected_is_superuser):
    """Helper method to verify Gateway user superuser status"""
    assert User.objects.filter(username=username).exists()
    assert User.objects.filter(username=username).get().is_superuser is expected_is_superuser


def _assert_service_user_superuser_status(service_client, username, expected_is_superuser):
    """Helper method to verify service user superuser status via API"""
    resource = service_client.list_resources(filters={"name": username}).json()
    assert resource["count"] == 1
    detail = service_client.get_resource(resource["results"][0]["ansible_id"]).json()
    assert detail["resource_data"]["is_superuser"] is expected_is_superuser


# =============================================================================
# Integration test fixtures
# =============================================================================


@pytest.fixture
def superuser_migration_controller_service(service_api_route_controller):
    proc = launch_test_service(svc_route=service_api_route_controller, fixture="controller_superuser_tests")
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def superuser_migration_hub_service(service_api_route_hub):
    proc = launch_test_service(
        svc_route=service_api_route_hub,
        fixture="hub_superuser_tests",
        svc_type="galaxy",
    )
    yield service_api_route_hub
    kill_test_service(proc)


@pytest.fixture
def superuser_migration_eda_service(service_api_route_eda):
    proc = launch_test_service(
        svc_route=service_api_route_eda,
        fixture="eda_superuser_tests",
        svc_type="eda",
    )
    yield service_api_route_eda
    kill_test_service(proc)


# =============================================================================
# test_multi_service_migration (integration)
# =============================================================================


@pytest.mark.django_db(transaction=True)
def test_multi_service_migration(
    superuser_migration_controller_service,
    service_api_route_controller,
    superuser_migration_hub_service,
    service_api_route_hub,
    superuser_migration_eda_service,
    service_api_route_eda,
    admin_user,
    patched_resource_client,
    patched_load_rbac,
    capsys,
):
    """Comprehensive test for superuser migration functionality across all services"""
    assert not User.objects.filter(username="controller_super").exists()
    assert not User.objects.filter(username="controller_regular").exists()

    call_command("migrate_service_data", username=admin_user.username)

    captured = capsys.readouterr()

    assert "Found 3 services to migrate" in captured.out
    assert f"Processing service: {service_api_route_controller.api_slug}" in captured.out
    assert f"Processing service: {service_api_route_hub.api_slug}" in captured.out
    assert f"Processing service: {service_api_route_eda.api_slug}" in captured.out
    assert "Successful migrations: 3" in captured.out
    assert "Failed migrations: 0" in captured.out
    assert "All services migration completed successfully!" in captured.out

    assert "Gateway superusers: ['admin', 'controller_super']" in captured.out
    assert "Controller superusers: ['admin', 'controller_super']" in captured.out
    assert "Controller and Gateway superusers are consistent" in captured.out

    assert "Demoted user 'hub_super' from superuser in hub" in captured.out
    assert "Demoted 1 users from superuser in hub: ['hub_super']" in captured.out

    _assert_gateway_user_superuser_status("controller_super", True)
    _assert_gateway_user_superuser_status("controller_regular", False)
    _assert_gateway_user_superuser_status("hub_super", False)
    _assert_gateway_user_superuser_status("hub_regular", False)
    _assert_gateway_user_superuser_status("eda_super", False)
    _assert_gateway_user_superuser_status("eda_regular", False)

    controller_client = patched_resource_client(service=superuser_migration_controller_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(controller_client, "controller_super", True)
    _assert_service_user_superuser_status(controller_client, "controller_regular", False)

    hub_client = patched_resource_client(service=superuser_migration_hub_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(hub_client, "hub_super", False)
    _assert_service_user_superuser_status(hub_client, "hub_regular", False)

    eda_client = patched_resource_client(service=superuser_migration_eda_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(eda_client, "eda_super", False)
    _assert_service_user_superuser_status(eda_client, "eda_regular", False)


# =============================================================================
# test_ensure_controller_gateway_superusers_scenarios (parameterized)
# =============================================================================


@pytest.mark.parametrize(
    "gateway_users,controller_users,expected_promotions,expected_errors,expected_output",
    [
        (
            [("controller_super_user", False)],
            [("admin", True), ("controller_super_user", True)],
            ["controller_super_user"],
            [],
            ["Promoted Gateway user 'controller_super_user' to superuser to match Controller status"],
        ),
        (
            [],
            [("admin", True), ("missing_user", True)],
            [],
            ["missing_user"],
            ["Error: Users ['missing_user'] are superusers in Controller but don't exist in Gateway"],
        ),
        (
            [],
            [("admin", True)],
            [],
            [],
            ["Controller and Gateway superusers are consistent"],
        ),
        (
            [("needs_promotion", False)],
            [("admin", True), ("needs_promotion", True), ("missing_user", True)],
            ["needs_promotion"],
            ["missing_user"],
            [
                "Promoted Gateway user 'needs_promotion' to superuser to match Controller status",
                "Error: Users ['missing_user'] are superusers in Controller but don't exist in Gateway",
            ],
        ),
    ],
)
@pytest.mark.django_db
def test_ensure_controller_gateway_superusers_scenarios(
    gateway_users,
    controller_users,
    expected_promotions,
    expected_errors,
    expected_output,
    admin_user,
    capsys,
    service_api_route_controller,
):
    """Parameterized test for _ensure_controller_gateway_superusers method scenarios"""
    created_users = {}
    for username, is_superuser in gateway_users:
        created_users[username] = User.objects.create(username=username, is_superuser=is_superuser)

    gateway_superusers = {"admin"}
    cmd = MigrateCommand()

    mock_client = Mock()

    list_results = []
    for i, (username, is_superuser) in enumerate(controller_users):
        ansible_id = f"ansible-id-{i}"
        list_results.append(
            {
                "ansible_id": ansible_id,
                "resource_data": {"username": username, "is_superuser": is_superuser},
            }
        )

    mock_client.list_resources.return_value.json.return_value = {
        "count": len(controller_users),
        "results": list_results,
        "next": None,
    }

    with patch(
        'aap_gateway_api.utils.resources_client.GWResourceAPIClient',
        return_value=mock_client,
    ):
        if expected_errors:
            from django.core.management.base import CommandError

            with pytest.raises(CommandError) as exc_info:
                cmd._ensure_controller_gateway_superusers(service_api_route_controller, gateway_superusers, admin_user)

            error_message = str(exc_info.value)
            assert "Migration failure detected" in error_message
            for missing_user in expected_errors:
                assert missing_user in error_message

        else:
            cmd._ensure_controller_gateway_superusers(service_api_route_controller, gateway_superusers, admin_user)

        for username in expected_promotions:
            user = created_users[username]
            user.refresh_from_db()
            assert user.is_superuser is True, f"User {username} should have been promoted to superuser"

        captured = capsys.readouterr()
        output = captured.out + captured.err
        for expected_msg in expected_output:
            assert expected_msg in output, f"Expected message '{expected_msg}' not found in output"


# =============================================================================
# _collect_controller_superusers tests
# =============================================================================


@pytest.fixture
def mock_controller_client(service_api_route_controller):
    mock_client = Mock()

    def run(page_data, resource_data, admin_user):
        def mock_list_resources(filters=None):
            page = filters["page"]
            response = page_data[page].copy()
            response["results"] = [{**item, **resource_data.get(item["ansible_id"], {})} for item in response["results"]]
            mock_response = Mock()
            mock_response.json.return_value = response
            return mock_response

        mock_client.list_resources.side_effect = mock_list_resources

        cmd = MigrateCommand()
        with patch(
            'aap_gateway_api.utils.resources_client.GWResourceAPIClient',
            return_value=mock_client,
        ):
            return cmd._collect_controller_superusers(service_api_route_controller, admin_user)

    yield mock_client, run


@pytest.mark.django_db
def test_collect_controller_superusers_single_page(admin_user, mock_controller_client):
    """Returns superuser usernames from a single page of results."""
    mock_client, run = mock_controller_client

    page_data = {
        1: {
            "results": [
                {"ansible_id": "id-1"},
                {"ansible_id": "id-2"},
                {"ansible_id": "id-3"},
            ],
            "next": None,
        },
    }
    resource_data = {
        "id-1": {"resource_data": {"username": "super_admin", "is_superuser": True}},
        "id-2": {"resource_data": {"username": "regular_user", "is_superuser": False}},
        "id-3": {"resource_data": {"username": "another_super", "is_superuser": True}},
    }

    result = run(page_data, resource_data, admin_user)
    assert result == {"super_admin", "another_super"}


@pytest.mark.django_db
def test_collect_controller_superusers_pagination(admin_user, mock_controller_client):
    """Handles paginated API responses correctly."""
    mock_client, run = mock_controller_client

    page_data = {
        1: {"results": [{"ansible_id": "id-1"}], "next": "http://example.com/page=2"},
        2: {"results": [{"ansible_id": "id-2"}], "next": None},
    }
    resource_data = {
        "id-1": {"resource_data": {"username": "super1", "is_superuser": True}},
        "id-2": {"resource_data": {"username": "super2", "is_superuser": True}},
    }

    result = run(page_data, resource_data, admin_user)

    assert result == {"super1", "super2"}
    mock_client.list_resources.assert_any_call(
        filters={
            "content_type__resource_type__name": "shared.user",
            "extra_fields": "resource_data",
            "page": 1,
        }
    )
    mock_client.list_resources.assert_any_call(
        filters={
            "content_type__resource_type__name": "shared.user",
            "extra_fields": "resource_data",
            "page": 2,
        }
    )
    assert mock_client.list_resources.call_count == 2


@pytest.mark.django_db
def test_collect_controller_superusers_no_superusers(admin_user, mock_controller_client):
    """Returns empty set when no superusers exist."""
    _, run = mock_controller_client

    page_data = {
        1: {
            "results": [{"ansible_id": "id-1"}, {"ansible_id": "id-2"}],
            "next": None,
        },
    }
    resource_data = {
        "id-1": {"resource_data": {"username": "user1", "is_superuser": False}},
        "id-2": {"resource_data": {"username": "user2", "is_superuser": False}},
    }

    result = run(page_data, resource_data, admin_user)
    assert result == set()


@pytest.mark.django_db
def test_collect_controller_superusers_empty_results(admin_user, mock_controller_client):
    """Handles empty results."""
    _, run = mock_controller_client

    page_data = {
        1: {"results": [], "next": None},
    }

    result = run(page_data, {}, admin_user)
    assert result == set()


# =============================================================================
# _demote_extra_superusers tests
# =============================================================================


@pytest.mark.django_db
def test_demote_extra_superusers_pagination(admin_user, service_api_route_hub, capsys):
    """Handles paginated results and demotes correctly."""
    cmd = MigrateCommand()
    mock_client = Mock()

    page_data = {
        1: {
            "results": [
                {
                    "ansible_id": "id-1",
                    "resource_data": {"username": "extra_super", "is_superuser": True},
                },
            ],
            "next": "http://example.com/page=2",
        },
        2: {
            "results": [
                {
                    "ansible_id": "id-2",
                    "resource_data": {"username": "normal_user", "is_superuser": False},
                },
            ],
            "next": None,
        },
    }

    def mock_list_resources(filters=None):
        page = filters["page"]
        mock_response = Mock()
        mock_response.json.return_value = page_data[page]
        return mock_response

    mock_client.list_resources.side_effect = mock_list_resources
    mock_client.update_resource.return_value = Mock()

    gateway_superusers = {"admin"}

    with patch(
        'aap_gateway_api.utils.resources_client.GWResourceAPIClient',
        return_value=mock_client,
    ):
        cmd._demote_extra_superusers(service_api_route_hub, gateway_superusers, admin_user)

    mock_client.update_resource.assert_called_once()
    assert mock_client.list_resources.call_count == 2

    captured = capsys.readouterr()
    assert "Demoted user 'extra_super'" in captured.out


# =============================================================================
# _get_gateway_user tests
# =============================================================================


@pytest.mark.django_db
def test_get_gateway_user_existing_user():
    """Returns the user when it exists."""
    test_user = User.objects.create(username="existing_user")

    cmd = MigrateCommand()
    result = cmd._get_gateway_user("existing_user")

    assert result == test_user
    assert result.username == "existing_user"


@pytest.mark.django_db
def test_get_gateway_user_nonexistent_user():
    """Returns None when user doesn't exist."""
    cmd = MigrateCommand()
    result = cmd._get_gateway_user("nonexistent_user")

    assert result is None


# =============================================================================
# _sync_controller_superuser tests
# =============================================================================


@pytest.mark.django_db
def test_sync_controller_superuser_promotes_existing_user(capsys):
    """Promotes existing non-superuser to superuser."""
    gateway_user = User.objects.create(username="controller_admin", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "controller_admin", upstream_is_superuser=True)

    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is True
    assert upstream_resource["resource_data"]["is_superuser"] is True

    captured = capsys.readouterr()
    assert "Promoted Gateway user 'controller_admin' to superuser based on Controller" in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_new_user_logs_creation(capsys):
    """Logs message for new user that will be created."""
    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "new_controller_admin", upstream_is_superuser=True)

    assert upstream_resource["resource_data"]["is_superuser"] is True

    captured = capsys.readouterr()
    assert "New user 'new_controller_admin' will be created with superuser status from Controller" in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_skips_non_superuser(capsys):
    """Does nothing when upstream user is not superuser."""
    gateway_user = User.objects.create(username="regular_user", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "regular_user", upstream_is_superuser=False)

    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is False
    assert upstream_resource["resource_data"]["is_superuser"] is False

    captured = capsys.readouterr()
    assert "Promoted" not in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_already_superuser(capsys):
    """Doesn't re-promote already superuser."""
    gateway_user = User.objects.create(username="existing_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "existing_admin", upstream_is_superuser=True)

    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is True
    assert upstream_resource["resource_data"]["is_superuser"] is True

    captured = capsys.readouterr()
    assert "Promoted" not in captured.out


# =============================================================================
# _sync_hub_eda_superuser tests
# =============================================================================


@pytest.mark.django_db
def test_sync_hub_eda_superuser_gateway_superuser(capsys):
    """Sets is_superuser=True when Gateway user is superuser."""
    User.objects.create(username="hub_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "hub_admin", upstream_is_superuser=False, service_type="hub")

    assert upstream_resource["resource_data"]["is_superuser"] is True

    captured = capsys.readouterr()
    assert "Gateway user is superuser: True" in captured.out
    assert "promoted to superuser in hub" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_demotes_non_gateway_superuser(capsys):
    """Demotes Hub/EDA superuser when Gateway user is not superuser."""
    User.objects.create(username="hub_regular", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "hub_regular", upstream_is_superuser=True, service_type="hub")

    assert upstream_resource["resource_data"]["is_superuser"] is False

    captured = capsys.readouterr()
    assert "Gateway user is superuser: False" in captured.out
    assert "demoted from superuser in hub" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_no_gateway_user(capsys):
    """Sets is_superuser=False when Gateway user doesn't exist."""
    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "missing_user", upstream_is_superuser=True, service_type="eda")

    assert upstream_resource["resource_data"]["is_superuser"] is False

    captured = capsys.readouterr()
    assert "Gateway user does not exist, will not be superuser" in captured.out
    assert "demoted from superuser in eda" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_no_change_needed(capsys):
    """Logs no change when status already matches."""
    User.objects.create(username="synced_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "synced_admin", upstream_is_superuser=True, service_type="hub")

    assert upstream_resource["resource_data"]["is_superuser"] is True

    captured = capsys.readouterr()
    assert "promoted to" not in captured.out
    assert "demoted from" not in captured.out
