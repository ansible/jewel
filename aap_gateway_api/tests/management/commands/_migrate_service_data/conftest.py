import uuid
from unittest.mock import Mock

import pytest

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import Organization, Route, Team
from aap_gateway_api.tests.service_test_app.launch import launch_service

SEP_CHAR = "_"


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


@pytest.fixture
def conflicting_org():
    org = Organization.objects.create(name="Org 1")
    yield org
    org.delete()


@pytest.fixture
def conflicting_team(conflicting_org):
    team = Team.objects.create(name="Team 1", organization=conflicting_org)
    yield team
    team.delete()


@pytest.fixture
def cmd(patched_resource_client):
    cmd = MigrateCommand()
    cmd.service_slug = 'controller'
    return cmd


def launch_test_service(svc_route: Route, fixture: str, svc_type: str = "awx", page_size=None):
    port = svc_route.service_port
    key = svc_route.service_cluster.generate_key()
    return launch_service(service_type=svc_type, port=port, setup_fixture=fixture, secret_key=key.secret, page_size=page_size)


def kill_test_service(proc):
    proc.kill()
    stdout, stderr = proc.communicate()
    if stdout:
        print('')
        print('standard out:')
        print(str(stdout, encoding='utf-8'))
    if stderr:
        print('')
        print('standard err:')
        print(str(stderr, encoding='utf-8'))


def setup_role_api_mocks(mock_client):
    """Helper function to setup common role types and permissions API mocks"""
    mock_types_response = Mock()
    mock_types_response.status_code = 200
    mock_types_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_types.return_value = mock_types_response

    mock_permissions_response = Mock()
    mock_permissions_response.status_code = 200
    mock_permissions_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_permissions.return_value = mock_permissions_response


def setup_empty_assignment_mocks(mock_client):
    """Setup empty role assignment mocks with proper HTTP response objects.

    The CursorStore-based pagination checks response.status_code before
    calling .json(), so assignment mocks must be explicit Mock objects
    with status_code=200.  Empty results signal the cursor that there
    are no new assignments beyond the current cursor position.
    """
    empty_user_resp = Mock()
    empty_user_resp.status_code = 200
    empty_user_resp.json.return_value = {"count": 0, "results": [], "next": None}
    mock_client.list_user_assignments.return_value = empty_user_resp

    empty_team_resp = Mock()
    empty_team_resp.status_code = 200
    empty_team_resp.json.return_value = {"count": 0, "results": [], "next": None}
    mock_client.list_team_assignments.return_value = empty_team_resp


def setup_basic_service_client_mocks(mock_client, service_api, admin_user, service_id=None, service_type="controller"):
    """Helper function to setup basic service client mocks with common configuration"""
    mock_client.service = service_api
    mock_client.user = admin_user
    mock_client.get_service_metadata.return_value.json.return_value = {
        "service_id": service_id or str(uuid.uuid4()),
        "service_type": service_type,
    }

    setup_role_api_mocks(mock_client)
    setup_empty_assignment_mocks(mock_client)


@pytest.fixture
def migration_service(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(svc_route=service_api_route_controller, fixture="migration_tests")
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def migration_service_invalid_users(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(svc_route=service_api_route_controller, fixture="migration_tests_invalid_users")
    yield service_api_route_controller
    kill_test_service(proc)


def assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client):
    from ansible_base.lib.utils.response import get_relative_url
    from ansible_base.resource_registry.models import service_id

    gw_service_id = str(service_id())
    service_api_route_controller.refresh_from_db()

    assert str(service_api_route_controller.service_cluster.service_id) == service_client.get_service_metadata().json()["service_id"]
    assert service_client.list_resources(filters={"service_id": gw_service_id}).json()["count"] != 0

    migrated_types = ["shared.organization", "shared.team"]
    resource_api_types = set()

    page = 1
    while True:
        resources = service_client.list_resources(filters={"page": page, "content_type__resource_type__name__in": ",".join(migrated_types)}).json()
        page += 1

        for resource in resources["results"]:
            resp = admin_api_client.get(get_relative_url("resource-detail", kwargs={"ansible_id": resource["ansible_id"]})).data
            resource = service_client.get_resource(resource["ansible_id"]).json()
            resource_api_types.add(resource["resource_type"])

            assert resp["ansible_id"] == resource["ansible_id"]
            assert resource["service_id"] == str(gw_service_id)
            assert resp["service_id"] == resource["service_id"]
            assert resp["name"] == resource["name"]

            for k in resource["resource_data"]:
                assert resource["resource_data"][k] == resp["resource_data"][k]
        if resources["next"] is None:
            break

    assert set(migrated_types) == resource_api_types

    resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "is_partially_migrated": "false",
        }
    ).json()
    assert resources["count"] == 1
