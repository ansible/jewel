import logging
import uuid
from collections import OrderedDict
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RemoteObject, RoleTeamAssignment, RoleUserAssignment
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.core.management import call_command
from django.db import IntegrityError

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import MigratedUserMetadata, Organization, Route, Team, User
from aap_gateway_api.tests.service_test_app.launch import launch_service

SEP_CHAR = "_"


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


# Friendly reminder to all who come after me, this test file uses test fixtures defined
# in module: aap_gateway_api/tests/service_test_app/fixtures/migration_tests.py
# It might not be obvious because the test fixtures are not imported, the name of the
# module is passed in as a parameter to launch_service() in migration_service fixture


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


def _launch_service(svc_route: Route, fixture: str, svc_type: str = "awx", page_size=None):
    port = svc_route.service_port
    key = svc_route.service_cluster.generate_key()
    return launch_service(service_type=svc_type, port=port, setup_fixture=fixture, secret_key=key.secret, page_size=page_size)


def _kill_service(proc):
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


def _setup_role_api_mocks(mock_client):
    """Helper function to setup common role types and permissions API mocks"""
    # Mock the list_role_types response
    mock_types_response = Mock()
    mock_types_response.status_code = 200
    mock_types_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_types.return_value = mock_types_response

    # Mock the list_role_permissions response
    mock_permissions_response = Mock()
    mock_permissions_response.status_code = 200
    mock_permissions_response.json.return_value = {"next": None, "results": []}
    mock_client.list_role_permissions.return_value = mock_permissions_response


def _setup_empty_assignment_mocks(mock_client):
    """Setup empty role assignment mocks with proper HTTP response objects.

    The _CursorStore-based pagination checks response.status_code before
    calling .json(), so assignment mocks must be explicit Mock objects
    with status_code=200.  Empty results signal the cursor that there
    are no new assignments beyond the current cursor position.
    """
    empty_user_resp = Mock()
    empty_user_resp.status_code = 200
    empty_user_resp.json.return_value = {"results": [], "next": None}
    mock_client.list_user_assignments.return_value = empty_user_resp

    empty_team_resp = Mock()
    empty_team_resp.status_code = 200
    empty_team_resp.json.return_value = {"results": [], "next": None}
    mock_client.list_team_assignments.return_value = empty_team_resp


def _setup_basic_service_client_mocks(mock_client, service_api, admin_user, service_id=None, service_type="controller"):
    """Helper function to setup basic service client mocks with common configuration"""

    mock_client.service = service_api
    mock_client.user = admin_user
    mock_client.get_service_metadata.return_value.json.return_value = {
        "service_id": service_id or str(uuid.uuid4()),
        "service_type": service_type,
    }

    # Setup role API mocks
    _setup_role_api_mocks(mock_client)

    # Setup empty assignment mocks with proper HTTP response objects
    _setup_empty_assignment_mocks(mock_client)


@pytest.fixture
def migration_service(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_invalid_users(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_invalid_users")
    yield service_api_route_controller
    _kill_service(proc)


def _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client):
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

    # check idempotence
    resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "is_partially_migrated": "false",
        }
    ).json()

    # _system user won't get synced
    assert resources["count"] == 1


@pytest.mark.django_db(transaction=True)
def test_migrate_with_ignored_flags(
    migration_service, admin_user, admin_api_client, conflicting_org, conflicting_team, patched_resource_client, patched_load_rbac, capsys
):
    """Test that deprecated flags are ignored with warnings and migration still works"""
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    # Test the command with ignored flags - it should now process only the migration_service
    # since that's the only DefaultServiceType service that exists in this test
    call_command("migrate_service_data", api_slug=migration_service.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=False)

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Capture stderr to check for warning messages
    captured = capsys.readouterr()
    assert "Warning: --api-slug flag is ignored" in captured.err
    assert "Warning: --merge-teams flag is ignored" in captured.err
    assert "Warning: --merge-organizations flag is ignored" in captured.err

    # With the new architecture, merge is always True, so orgs should be merged, not renamed
    # The conflicting org should still exist with the original name
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    # There should NOT be a renamed org since merge=True is the new default
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    # Teams should also be merged since merge=True is the default
    original_org_teams = list(conflicting_org.teams.all().values_list("name", flat=True))
    assert original_org_teams == [conflicting_team.name]


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
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    # Test that merge flags are ignored and behavior is always merge=True
    call_command(
        "migrate_service_data",
        username=admin_user.username,
        merge_teams=False,
        merge_organizations=False,
    )

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Both orgs and teams should be merged regardless of flags since merge is always True
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    # Teams should also be merged since merge=True is always enforced
    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(organization=conflicting_org, name=migration_service.api_slug + SEP_CHAR + conflicting_team.name).exists()


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
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Check that only one organization exists (merged)
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    # Teams should also be merged by default
    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(organization=conflicting_org, name=migration_service.api_slug + SEP_CHAR + conflicting_team.name).exists()


@pytest.mark.django_db(transaction=True)
def test_migrate_conflicting_user(
    migration_service,
    admin_user,
    admin_api_client,
    patched_resource_client,
    patched_load_rbac,
):
    # Check that users do not exist yet
    assert not User.objects.filter(username="natasha").exists()
    assert not User.objects.filter(username="hawkeye").exists()

    # Create a conflict with a different service (we'll use a fake service ID for this conflict)
    from aap_gateway_api.models import ServiceCluster, ServiceType

    # Create a fake service for the conflict
    fake_service_type = ServiceType.objects.create(name="fake")
    fake_service_cluster = ServiceCluster.objects.create(name="fake", service_type=fake_service_type)

    u = User.objects.create(username="hawkeye")
    MigratedUserMetadata.objects.create(user=u, service=fake_service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    # Since migration_service is the only DefaultServiceType service in this test,
    # the command will naturally process only that service
    call_command(
        "migrate_service_data",
        username=admin_user.username,
    )

    pre_sync_resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "content_type__resource_type__name": "shared.user",
            "not__name": admin_user.username,  # admin user will be merged, and thus get the gateway service_id
        }
    ).json()

    assert len(pre_sync_resources['results']) > 0

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Check that users were migrated, they were created in the migration_tests script
    assert User.objects.filter(username="natasha").exists()
    assert User.objects.filter(username="hawkeye").exists()

    # With AAP-47840 implementation, conflicting users are merged instead of renamed
    # So no renamed user with service prefix should be created
    assert not User.objects.filter(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').exists()

    # The original hawkeye user should still exist (merged behavior)
    hawkeye_user = User.objects.get(username="hawkeye")

    # The original account metadata created in test setup should still exist
    assert hawkeye_user.original_accounts.count() == 1  # Original metadata should remain

    # With the new AAP-47840 merging behavior, the hawkeye user should be merged
    # Check that the resource was properly updated
    updated_resource = service_client.get_resource(str(hawkeye_user.resource.ansible_id)).json()
    assert updated_resource

    # With AAP-47840, users are fully migrated (is_partially_migrated=False)
    assert updated_resource["is_partially_migrated"] is False

    # We set is_partially_migrated=True for this user in the fixture, so it should not get migrated
    assert not User.objects.filter(username="already_migrated").exists()

    # With merging behavior, the hawkeye user should have Gateway's service_id
    assert hawkeye_user.resource.service_id != migration_service.service_cluster.service_id

    from ansible_base.resource_registry.models import service_id

    gateway_service_id = service_id()
    assert str(hawkeye_user.resource.service_id) == gateway_service_id


@pytest.mark.django_db(transaction=True)
def test_merge_users(
    migration_service,
    admin_user,
    admin_api_client,
    patched_resource_client,
    patched_load_rbac,
):
    # Create a conflict with a different service (we'll use a fake service ID for this conflict)
    from aap_gateway_api.models import ServiceCluster, ServiceType

    # Create a fake service for the conflict
    fake_service_type = ServiceType.objects.create(name="fake")
    fake_service_cluster = ServiceCluster.objects.create(name="fake", service_type=fake_service_type)

    u = User.objects.create(username="hawkeye", email="hawkeye@secretbase.invalid")
    MigratedUserMetadata.objects.create(user=u, service=fake_service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    # Since migration_service is the only DefaultServiceType service in this test,
    # the command will naturally process only that service
    call_command(
        "migrate_service_data",
        username=admin_user.username,
    )
    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Check that users were migrated, they were created in the migration_tests script
    assert User.objects.filter(username="hawkeye").exists()

    # With AAP-47840 merging behavior, no renamed user should be created
    assert not User.objects.filter(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').exists()

    # The original hawkeye user should still have the original account metadata from test setup
    hawkeye_user = User.objects.get(username="hawkeye")
    assert hawkeye_user.original_accounts.count() == 1

    # Check that the hawkeye user was properly merged
    updated_resource = service_client.get_resource(str(hawkeye_user.resource.ansible_id)).json()
    assert updated_resource

    # With AAP-47840, users are fully migrated (is_partially_migrated=False)
    assert updated_resource["is_partially_migrated"] is False

    # The username should remain unchanged (no service prefix)
    updated_user = updated_resource['resource_data']
    assert updated_user.get('username') == 'hawkeye', updated_user

    # We set is_partially_migrated=True for this user in the fixture, so it should not get migrated
    assert not User.objects.filter(username="already_migrated").exists()


@pytest.mark.django_db(transaction=True)
def test_correcting_user_service_id(
    migration_service,
    admin_user,
    patched_resource_client,
    patched_load_rbac,
):
    """Verify that a service user resource with the same ansible id but a differing
    service id from gateway's has its service id corrected to gateway's via migration.
    """
    # First, perform a migration to bring our test user ("fury") to gateway.
    # The migration preserves
    # Since migration_service is the only DefaultServiceType service in this test,
    # the command will naturally process only that service
    call_command(
        "migrate_service_data",
        username=admin_user.username,
    )

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    # Get the service-side user resource and set its is_partially_migrated flag as False.
    response = service_client.list_resources(filters={"name": "fury"})
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    service_fury_resource_data = result["results"][0]
    service_client.update_resource(
        service_fury_resource_data["ansible_id"],
        ResourceRequestBody(**{"is_partially_migrated": False}),
        partial=True,
    )

    # Get the gateway user resource and force its service id to be gateway's.
    # Combining this with the above setting of the service-side user resource's
    # is_partially_migrated flag as False mimics the scenario where the service
    # user resource has been automatically instantiated with a different
    # service id than gateway's.
    gw_fury_resource = Resource.objects.get(name="fury")
    gw_fury_resource.service_id = service_id()
    gw_fury_resource.save(update_fields=["service_id"])

    # Run an additional migration which should correct the service-side user
    # resource's server_id to that of gateway.
    # First, perform a migration to bring our test user ("fury") to gateway.
    # The migration preserves
    # Since migration_service is the only DefaultServiceType service in this test,
    # the command will naturally process only that service
    call_command(
        "migrate_service_data",
        username=admin_user.username,
    )

    # Retrieve the service-side user resource and verify its service id is now
    # gateway's.
    response = service_client.list_resources(filters={"name": "fury"})
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    service_fury_resource_data = result["results"][0]
    assert service_fury_resource_data["service_id"] == service_id()


@pytest.mark.django_db(transaction=True)
def test_migrating_user_with_invalid_email(migration_service_invalid_users, admin_user, patched_load_rbac):
    # Since migration_service_invalid_users is the only DefaultServiceType service in this test,
    # the command will naturally process only that service
    cmd = MigrateCommand()
    cmd.service_slug = 'controller'

    call_command(cmd, username=admin_user.username)

    users = User.objects.filter(username="bademailuser1")
    assert users is not None and users.exists()
    for u in users:
        assert u.first_name == "Badema"
        assert u.last_name == "Iluser"
        assert u.email == ""


@pytest.mark.django_db(transaction=True)
def test_updating_resource_data_for_invalid_resource(migration_service_invalid_users, patched_load_rbac, admin_user):
    from django.core.management.base import CommandError

    with patch.object(MigrateCommand, "update_resource_data") as mocked_update_resource_data_method:
        mocked_update_resource_data_method.return_value = None  # None indicates that its data could not be updated

        # Since migration_service_invalid_users is the only DefaultServiceType service in this test,
        # the command will naturally process only that service
        cmd = MigrateCommand()
        cmd.service_slug = 'controller'

        # With the new architecture, RuntimeError gets caught and re-thrown as CommandError
        with pytest.raises(CommandError):
            call_command(cmd, username=admin_user.username)

            assert not User.objects.filter(username="invaliduser").exists()
            assert not User.objects.filter(username="bademailuser1").exists()


@pytest.fixture
def cmd(patched_resource_client):
    cmd = MigrateCommand()
    cmd.service_slug = 'controller'
    return cmd


@pytest.mark.django_db
def test_use_given_name_first_found(cmd):
    # assert that the first argument takes precedence when the name-like field is given in unique fields
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser'

    # If user bob exists that should not affect the result
    User.objects.create(username='bob')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser'


@pytest.mark.django_db
def test_use_given_name_iteration(cmd):
    User.objects.create(username='controller_foouser')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser1'

    User.objects.create(username='controller_foouser1')
    User.objects.create(username='controller_foouser2')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser3'


@pytest.mark.django_db(transaction=True)
def test_service_processing_order(admin_user, capsys, service_api_route_controller, service_api_route_hub, service_api_route_eda, patched_resource_client):
    """Test that services are processed in exact order: controller, hub, eda"""

    # Mock the client to fail early so we can see the processing order in stdout
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_client = Mock()
        mock_client.get_service_metadata.side_effect = Exception("Test order tracking")
        mock_client_class.return_value = mock_client

        # Should process all three services and fail on each, but in the right order
        with pytest.raises(Exception):
            call_command("migrate_service_data", username=admin_user.username)

        # Check the output for service processing order
        captured = capsys.readouterr()
        output_lines = captured.out.split('\n')

        # Find lines that show service processing order
        processing_lines = [line for line in output_lines if "Processing service:" in line]

        # Should have all three services processed in order - we check by service type, not api_slug
        assert len(processing_lines) == 3, output_lines
        # Extract service objects to check their service type order
        assert service_api_route_controller.service_cluster.service_type.name == "controller"
        assert service_api_route_hub.service_cluster.service_type.name == "hub"
        assert service_api_route_eda.service_cluster.service_type.name == "eda"

        # Check that controller's api_slug appears first, then hub's, then eda's
        assert service_api_route_controller.api_slug in processing_lines[0]  # Controller first
        assert service_api_route_hub.api_slug in processing_lines[1]  # Hub second
        assert service_api_route_eda.api_slug in processing_lines[2]  # EDA third


@pytest.mark.django_db(transaction=True)
def test_migration_error_handling_and_summary(admin_user, capsys, service_api_route_controller, service_api_route_hub, patched_resource_client, system_user):
    """Test error handling and migration summary for mixed success/failure scenarios"""

    # Mock the client to succeed for controller but fail for hub
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        from requests.exceptions import HTTPError

        # Mock JWT creation to avoid public key parsing issues
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'

        def mock_client_factory(service_api, *args, **kwargs):
            mock_client = Mock()
            mock_client.service = service_api
            mock_client.user = admin_user

            if service_api.service_cluster.service_type.name == "controller":
                # Controller succeeds
                mock_client.get_service_metadata.return_value.json.return_value = {
                    "service_id": str(uuid.uuid4()),  # Generate proper UUID
                    "service_type": "controller",
                }
                # Mock successful migration workflow
                mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
                _setup_empty_assignment_mocks(mock_client)
            else:
                # Hub fails
                mock_client.get_service_metadata.side_effect = HTTPError("Mock HTTP error")
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        # Migration should fail with CommandError due to failed hub service
        with pytest.raises(Exception) as exc_info:
            call_command("migrate_service_data", username=admin_user.username)

        # Check error message contains service failure information
        error_message = str(exc_info.value)
        assert "Migration failed" in error_message
        assert service_api_route_hub.api_slug in error_message

        # Check that migration summary was printed
        captured = capsys.readouterr()
        assert "=== Migration Summary ===" in captured.out
        assert "Successful migrations: 1" in captured.out
        assert "Failed migrations: 1" in captured.out
        assert "Failed to migrate the following services:" in captured.err
        assert service_api_route_hub.api_slug in captured.err


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
            mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
            _setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" in captured.out
        assert "skipping resource migration" in captured.out
        # Resource migration is skipped but role assignments still run
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
            mock_client.list_resources.return_value.json.return_value = {"count": 1, "results": []}
            _setup_empty_assignment_mocks(mock_client)
            return mock_client

        mock_client_class.side_effect = mock_client_factory

        call_command("migrate_service_data", username=admin_user.username)

        captured = capsys.readouterr()
        assert "already synchronized" not in captured.out
        assert "Migrating data for" in captured.out


@pytest.mark.django_db(transaction=True)
def test_migration_uses_bulk_fetch(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test that migration uses list_resources with extra_fields instead of individual get_resource calls."""

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
            # First call returns count=1 so _is_service_already_synced() returns False
            # and migration proceeds. Subsequent calls return count=0 so the
            # migrate_resource loop exits immediately.
            responses = [Mock(json=Mock(return_value={"count": 1, "results": []}))]
            responses += [Mock(json=Mock(return_value={"count": 0, "results": []}))] * 20
            mock_client.list_resources.side_effect = responses
            _setup_empty_assignment_mocks(mock_client)
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


@pytest.mark.django_db
def test_process_migrate_resource_item_raises_on_missing_resource_data():
    """Test that _process_and_migrate_resource_item raises when resource_data is missing."""
    cmd = MigrateCommand()
    resource_item = {"ansible_id": "test-id-123", "name": "test"}
    resource_context = {"type": Mock()}

    with pytest.raises(RuntimeError, match="missing 'resource_data'"):
        cmd._process_and_migrate_resource_item(resource_item, resource_context)


@pytest.mark.django_db(transaction=True)
def test_no_services_found_error(admin_user):
    """Test error when no DefaultServiceType services are found"""
    # In a clean test environment with no service fixtures, the command should fail
    with pytest.raises(Exception) as exc_info:
        call_command("migrate_service_data", username=admin_user.username)

    assert "No services found with expected service types" in str(exc_info.value)


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


@pytest.fixture
def superuser_migration_controller_service(service_api_route_controller):
    """Launch a controller service with controller-specific superuser test data"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="controller_superuser_tests")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def superuser_migration_hub_service(service_api_route_hub):
    """Launch a hub service with hub-specific superuser test data"""
    proc = _launch_service(svc_route=service_api_route_hub, fixture="hub_superuser_tests", svc_type="galaxy")
    yield service_api_route_hub
    _kill_service(proc)


@pytest.fixture
def superuser_migration_eda_service(service_api_route_eda):
    """Launch an EDA service with EDA-specific superuser test data"""
    proc = _launch_service(svc_route=service_api_route_eda, fixture="eda_superuser_tests", svc_type="eda")
    yield service_api_route_eda
    _kill_service(proc)


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

    # Verify initial state - Controller users don't exist in Gateway yet
    assert not User.objects.filter(username="controller_super").exists()
    assert not User.objects.filter(username="controller_regular").exists()

    # === Migration Phase: Run migration once for all services ===
    call_command("migrate_service_data", username=admin_user.username)

    captured = capsys.readouterr()

    # === Verify migration output ===
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

    # === Verify gateway users ===
    # Controller users: superuser promoted, regular remains regular
    _assert_gateway_user_superuser_status("controller_super", True)  # Synced from controller to gateway as superuser
    _assert_gateway_user_superuser_status("controller_regular", False)  # Synced from controller to gateway as regular user
    _assert_gateway_user_superuser_status("hub_super", False)  # Synced from hub to gateway as regular user
    _assert_gateway_user_superuser_status("hub_regular", False)  # Synced from hub to gateway as regular user
    _assert_gateway_user_superuser_status("eda_super", False)  # Synced from EDA to gateway as regular user
    _assert_gateway_user_superuser_status("eda_regular", False)  # Synced from EDA to gateway as regular user

    # === Verify service users ===
    controller_client = patched_resource_client(service=superuser_migration_controller_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(controller_client, "controller_super", True)  # Should remain superuser
    _assert_service_user_superuser_status(controller_client, "controller_regular", False)  # Should remain regular

    hub_client = patched_resource_client(service=superuser_migration_hub_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(hub_client, "hub_super", False)  # Should be demoted to regular
    _assert_service_user_superuser_status(hub_client, "hub_regular", False)  # Should remain regular

    eda_client = patched_resource_client(service=superuser_migration_eda_service, user=admin_user, raise_if_bad_request=True)
    _assert_service_user_superuser_status(eda_client, "eda_super", False)  # Should be demoted to regular
    _assert_service_user_superuser_status(eda_client, "eda_regular", False)  # Should remain regular


@pytest.mark.django_db(transaction=True)
def test_single_service_migration(admin_user, capsys, service_api_route_controller, patched_resource_client, system_user):
    """Test migration with only a single service available"""

    # Use a deterministic slug so random hex can't contain "eda" or "hub"
    service_api_route_controller.api_slug = "test-controller-slug"
    service_api_route_controller.gateway_path = "/api/test-controller-slug/"
    service_api_route_controller.save()

    # Mock successful migration for the controller service
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        # Mock JWT creation to avoid public key parsing issues
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        # Mock consistency check to avoid superuser validation issues
        mock_consistency_check.return_value = None

        mock_client = Mock()
        _setup_basic_service_client_mocks(mock_client, service_api_route_controller, admin_user)

        # Mock empty resource lists for clean migration
        mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
        # Assignment mocks already set by _setup_basic_service_client_mocks
        mock_client_class.return_value = mock_client

        # Should successfully process the single service
        call_command("migrate_service_data", username=admin_user.username)

        # Check that only the controller service was processed
        captured = capsys.readouterr()
        assert "Found 1 services to migrate" in captured.out
        assert f"Processing service: {service_api_route_controller.api_slug}" in captured.out
        assert "Successful migrations: 1" in captured.out
        assert "Failed migrations: 0" in captured.out
        assert "All services migration completed successfully!" in captured.out

        assert "hub" not in captured.out
        assert "eda" not in captured.out


@pytest.mark.django_db(transaction=True)
def test_duplicate_email_on_same_authenticator_should_fail(admin_user, admin_api_client, local_authenticator):
    """Test that two users cannot have the same email address on the same authenticator.

    Steps to recreate the issue:
    1. Create two users: user1, user2
    2. Create an authenticator
    3. Assign the authenticator to user1 with email address foo@test.com
    4. Assign the authenticator to user2 with email address foo@test.com

    Expected behavior: The second assignment should return an error
    """
    # Create two users
    user1 = User.objects.create(username="user1", email="user1@example.com")
    user2 = User.objects.create(username="user2", email="user2@example.com")

    # Assign the authenticator to user1 with email address foo@test.com
    AuthenticatorUser.objects.create(user=user1, provider=local_authenticator, email="foo@test.com")

    # Attempt to assign the same authenticator to user2 with the same email address foo@test.com
    # This should raise an error
    with pytest.raises((IntegrityError, Exception)) as exc_info:
        AuthenticatorUser.objects.create(user=user2, provider=local_authenticator, email="foo@test.com")

    # The error should indicate a constraint violation or duplicate/unique constraint
    error_message = str(exc_info.value).lower()
    assert any(keyword in error_message for keyword in ["duplicate", "unique", "constraint", "already exists"]), (
        f"Expected error message to indicate constraint violation, got: {exc_info.value}"
    )

    # Verify that only the first user has the authenticator with the email
    assert AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com").count() == 1
    assert AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com", user=user1).exists()
    assert not AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com", user=user2).exists()


# Legacy Authenticator Delete Tests
@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_no_legacy_authenticators(admin_user, capsys):
    """Test delete when no legacy authenticators exist"""

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    captured = capsys.readouterr()
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_password' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_external_password' found" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_with_controller_admin(admin_user, capsys):
    """Test delete of controller admin authenticators"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    legacy_auth = Authenticator.objects.create(
        name="Legacy Controller Admin",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin")
    legacy_auth.refresh_from_db()

    # Create some users linked to this authenticator
    user1 = User.objects.create(username="test_user1")
    user2 = User.objects.create(username="test_user2")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth, uid="test_user1")
    AuthenticatorUser.objects.create(user=user2, provider=legacy_auth, uid="test_user2")

    # Verify setup
    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 2
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 1

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    # Verify delete
    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' to clean up" in captured.out
    assert "Unlinking 2 users from legacy authenticator 'Legacy Controller Admin'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Controller Admin'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_multiple_types(admin_user, capsys):
    """Test delete of multiple legacy authenticator types"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    # Create authenticators with valid types first, then manually change their type to legacy types
    # This avoids module loading issues during creation
    legacy_auth1 = Authenticator.objects.create(
        name="Legacy SSO",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth1.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth1.refresh_from_db()

    legacy_auth2 = Authenticator.objects.create(
        name="Legacy Password",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth2.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_password")
    legacy_auth2.refresh_from_db()

    legacy_auth3 = Authenticator.objects.create(
        name="Legacy External Password",
        type="ansible_base.authentication.authenticator_plugins.ldap",  # Valid type for creation
        enabled=True,
        configuration={},
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth3.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_external_password")
    legacy_auth3.refresh_from_db()

    # Create some users linked to these authenticators
    user1 = User.objects.create(username="sso_user")
    user2 = User.objects.create(username="password_user")
    user3 = User.objects.create(username="external_user")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth1, uid="sso_user")
    AuthenticatorUser.objects.create(user=user2, provider=legacy_auth2, uid="password_user")
    AuthenticatorUser.objects.create(user=user3, provider=legacy_auth3, uid="external_user")

    # Verify setup
    assert AuthenticatorUser.objects.count() == 3
    assert Authenticator.objects.filter(type__startswith="aap_gateway_api.authentication.authenticator_plugins.legacy").count() == 3

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    # Verify delete
    assert AuthenticatorUser.objects.count() == 0
    assert Authenticator.objects.filter(type__startswith="aap_gateway_api.authentication.authenticator_plugins.legacy").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' to clean up" in captured.out
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_password' to clean up" in captured.out
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_external_password' to clean up" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy SSO'" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy Password'" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy External Password'" in captured.out
    assert "Deleting legacy authenticator 'Legacy SSO'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Password'" in captured.out
    assert "Deleting legacy authenticator 'Legacy External Password'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_no_users(admin_user, capsys):
    """Test delete of legacy authenticators with no associated users"""
    from ansible_base.authentication.models import Authenticator

    # Create authenticator with valid type first, then manually change to legacy type
    # This avoids module loading issues during creation
    legacy_auth = Authenticator.objects.create(
        name="Unused Legacy Auth",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth.refresh_from_db()

    # Verify setup
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 1

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    # Verify delete
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' to clean up" in captured.out
    # Should not have any "Unlinking" messages since no users were linked
    assert "Unlinking" not in captured.out
    assert "Deleting legacy authenticator 'Unused Legacy Auth'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_preserves_non_legacy(admin_user, capsys):
    """Test that delete only unlinks users from legacy authenticators and preserves non-legacy ones"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    # Create authenticator with valid type first, then manually change to legacy type
    # This avoids module loading issues during creation
    legacy_auth = Authenticator.objects.create(
        name="Legacy Auth",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Manually update the type to legacy type to avoid module loading
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth.refresh_from_db()

    # Create a non-legacy authenticator (should be preserved)
    non_legacy_auth = Authenticator.objects.create(
        name="Modern Auth", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}
    )

    # Create users linked to both authenticators
    user1 = User.objects.create(username="legacy_user")
    user2 = User.objects.create(username="modern_user")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth, uid="legacy_user")
    AuthenticatorUser.objects.create(user=user2, provider=non_legacy_auth, uid="modern_user")

    # Verify setup
    assert AuthenticatorUser.objects.count() == 2
    assert Authenticator.objects.count() == 2

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    # Verify delete
    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
    assert AuthenticatorUser.objects.filter(provider=non_legacy_auth).count() == 1
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 0
    assert Authenticator.objects.filter(type="ansible_base.authentication.authenticator_plugins.ldap").count() == 1

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' to clean up" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy Auth'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Auth'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_integration_with_migration(admin_user, capsys, service_api_route_controller, patched_resource_client):
    """Test that legacy authenticator delete is called during migration"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    # Create a legacy authenticator that should be cleaned up during migration
    legacy_auth = Authenticator.objects.create(
        name="Legacy Controller Admin",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin")
    legacy_auth.refresh_from_db()

    user = User.objects.create(username="legacy_user")
    AuthenticatorUser.objects.create(user=user, provider=legacy_auth, uid="legacy_user")

    # Mock successful migration
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        # Mock consistency check to avoid superuser validation issues
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
        _setup_empty_assignment_mocks(mock_client)
        mock_client_class.return_value = mock_client

        # Run migration
        call_command("migrate_service_data", username=admin_user.username)

        # Verify delete
        assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
        assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 0

        captured = capsys.readouterr()
        assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' to clean up" in captured.out
        assert "Unlinking 1 users from legacy authenticator 'Legacy Controller Admin'" in captured.out
        assert "Deleting legacy authenticator 'Legacy Controller Admin'" in captured.out


@pytest.fixture
def comprehensive_migration_controller_service(service_api_route_controller):
    """Launch a controller service with comprehensive migration test data."""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="comprehensive_migration_controller")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def comprehensive_migration_hub_service(service_api_route_hub):
    """Launch a hub service with comprehensive migration test data."""
    proc = _launch_service(svc_route=service_api_route_hub, fixture="comprehensive_migration_hub", svc_type="galaxy")
    yield service_api_route_hub
    _kill_service(proc)


@pytest.fixture
def comprehensive_migration_eda_service(service_api_route_eda):
    """Launch an EDA service with comprehensive migration test data."""
    proc = _launch_service(svc_route=service_api_route_eda, fixture="comprehensive_migration_eda", svc_type="eda")
    yield service_api_route_eda
    _kill_service(proc)


@pytest.mark.django_db(transaction=True)
def test_comprehensive_multi_service_migration(
    comprehensive_migration_controller_service,
    comprehensive_migration_hub_service,
    comprehensive_migration_eda_service,
    admin_user,
    patched_resource_client,
    patched_load_rbac,
    capsys,
):
    """
    Comprehensive test for AAP-47840 multi-service user migration covering all manual test scenarios:

    Test Case 1: controller-only-user (Controller only)
    Test Case 2: controller-hub-user (Controller + Hub)
    Test Case 3: hub-eda-user (Hub + EDA)
    Test Case 4: all-services-user (Controller + Hub + EDA)
    """

    controller_client = patched_resource_client(service=comprehensive_migration_controller_service, user=admin_user, raise_if_bad_request=True)
    hub_client = patched_resource_client(service=comprehensive_migration_hub_service, user=admin_user, raise_if_bad_request=True)
    eda_client = patched_resource_client(service=comprehensive_migration_eda_service, user=admin_user, raise_if_bad_request=True)

    gateway_service_id = str(service_id())

    # Verify initial state - no Gateway users exist initially
    assert not User.objects.filter(username="controller-only-user").exists()
    assert not User.objects.filter(username="controller-hub-user").exists()
    assert not User.objects.filter(username="hub-eda-user").exists()
    assert not User.objects.filter(username="all-services-user").exists()

    # Run migration for all services
    call_command("migrate_service_data", username=admin_user.username)

    captured = capsys.readouterr()

    # === Verify migration output ===
    assert "Found 3 services to migrate" in captured.out
    assert "Merging partially migrated users" in captured.out
    assert "Successful migrations: 3" in captured.out
    assert "Failed migrations: 0" in captured.out
    assert "All services migration completed successfully!" in captured.out

    # === Test Case 1: controller-only-user - Should only exist in Controller ===
    # gateway user verification
    gateway_user_list = User.objects.filter(username__endswith="controller-only-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="controller-only-user")
    assert gateway_user.email == "controller@example.com"
    assert gateway_user.first_name == "Controller"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    # gateway resource verification
    gateway_resource_list = Resource.objects.filter(name__endswith="controller-only-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    # controller resource verification
    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    # hub resource verification
    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert hub_resource_list["count"] == 0

    # eda resource verification
    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert eda_resource_list["count"] == 0

    # === Test Case 2: controller-hub-user - Should exist in Controller and Hub, NOT in EDA ===
    # gateway user verification
    gateway_user_list = User.objects.filter(username__endswith="controller-hub-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="controller-hub-user")
    assert gateway_user.email == "multi@example.com"
    assert gateway_user.first_name == "Multi"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    # gateway resource verification
    gateway_resource_list = Resource.objects.filter(name__endswith="controller-hub-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    # controller resource verification
    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    # hub resource verification
    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    # eda resource verification
    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert eda_resource_list["count"] == 0

    # === Test Case 3: hub-eda-user - Should exist in Hub and EDA, NOT in Controller ===
    # gateway user verification
    gateway_user_list = User.objects.filter(username__endswith="hub-eda-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="hub-eda-user")
    assert gateway_user.email == "hubeda@example.com"
    assert gateway_user.first_name == "HubEda"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    # gateway resource verification
    gateway_resource_list = Resource.objects.filter(name__endswith="hub-eda-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    # controller resource verification
    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert controller_resource_list["count"] == 0

    # hub resource verification
    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    # eda resource verification
    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert eda_resource_list["count"] == 1
    eda_resource = eda_client.get_resource(eda_resource_list["results"][0]["ansible_id"]).json()
    assert eda_resource["ansible_id"] == gateway_resource_ansible_id
    assert eda_resource["service_id"] == gateway_service_id
    assert eda_resource["is_partially_migrated"] is False

    # === Test Case 4: all-services-user - Should exist in all services ===
    # gateway user verification
    gateway_user_list = User.objects.filter(username__endswith="all-services-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="all-services-user")
    assert gateway_user.email == "allservices@example.com"
    assert gateway_user.first_name == "AllServices"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    # gateway resource verification
    gateway_resource_list = Resource.objects.filter(name__endswith="all-services-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    # controller resource verification
    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    # hub resource verification
    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    # eda resource verification
    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert eda_resource_list["count"] == 1
    eda_resource = eda_client.get_resource(eda_resource_list["results"][0]["ansible_id"]).json()
    assert eda_resource["ansible_id"] == gateway_resource_ansible_id
    assert eda_resource["service_id"] == gateway_service_id
    assert eda_resource["is_partially_migrated"] is False

    # ==== Final validation - no partially migrated user in any service ====
    gateway_resource_list = Resource.objects.filter(content_type__resource_type__name="shared.user", is_partially_migrated=True)
    assert gateway_resource_list.count() == 0

    controller_resource_list = controller_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert controller_resource_list["count"] == 0

    hub_resource_list = hub_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert hub_resource_list["count"] == 0

    eda_resource_list = eda_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert eda_resource_list["count"] == 0


@pytest.fixture
def migration_service_controller_roles_paginated(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    """Launch a controller service with controller-specific role assignment test data that requires pagination"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_roles_pagination", page_size=10)
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_controller_roles(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    """Launch a controller service with controller-specific role assignment test data"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_roles")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_controller_roles_duplicate_teams(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    """Launch a controller service with controller-specific role assignment test data across duplicate team names"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_roles_duplicate_teams")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_controller_roles_remoteobject(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    """Launch a controller service with controller-specific role assignment test data across duplicate team names"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_roles_remoteobject")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_hub_roles(patched_resource_client, service_api_route_hub, ensure_jwt_keys):
    """Launch a hub service with hub-specific role assignment test data"""
    proc = _launch_service(svc_route=service_api_route_hub, fixture="migration_tests_hub_roles", svc_type="galaxy")
    yield service_api_route_hub
    _kill_service(proc)


def _user_assignment_exists(username, role_definition_name, object_name) -> bool:
    """Helper function to check if an assignment exists in gateway post-migration"""
    assignment = RoleUserAssignment.objects.filter(user__username=username, role_definition__name=role_definition_name).first()
    if assignment:
        if object_name is not None:
            return assignment.content_object.name == object_name  # type: ignore
        else:
            return assignment.content_object is None
    else:
        return False


@pytest.mark.django_db()
def test_controller_role_assignment_migration(migration_service_controller_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated"""

    # migration_service_controller_roles creates users in controller with org admin, org member, team admin, team member
    service_client = patched_resource_client(service=migration_service_controller_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    _assert_all_resources_synced(admin_api_client, migration_service_controller_roles, service_client)

    for assignment in (
        ('controller-organization-admin', 'Organization Admin', 'controller-admin-organization'),
        ('controller-organization-member', 'Organization Member', 'controller-member-organization'),
        ('controller-team-admin', 'Team Admin', 'controller-admin-team'),
        ('controller-team-member', 'Team Member', 'controller-member-team'),
        ('controller-platform-auditor', 'Platform Auditor', None),
        ('controller-dummy-user', 'controller-dummy-role', 'controller-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])


@pytest.mark.django_db()
def test_controller_role_assignment_migration_reinstall_is_noop(
    migration_service_controller_roles, admin_user, admin_api_client, patched_resource_client, capsys
):
    """Test that running migrate_service_data a second time with already-synced data
    completes with zero give_permission calls (set-diff produces an empty delta).

    This is the core performance scenario for AAP-78674: at scale (86K+ role
    assignments), a reinstall was taking 4+ hours because every assignment was
    re-fetched and re-processed even though all data already matched. The set-diff
    approach computes to_create = remote - local; when the sets match, to_create
    is empty and no work is done.

    The test runs the full migration command end-to-end against a real test
    service and database:
      1. First run: fresh install — assignments are created normally
      2. Reset the migration-complete flag so the command will run again
      3. Second run: reinstall — all assignments already exist, expect "0 assignments created"
    """
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    # --- First run: fresh install, assignments are created ---
    patched_resource_client(service=migration_service_controller_roles, user=admin_user, raise_if_bad_request=True)
    call_command("migrate_service_data", username=admin_user.username)

    # Verify assignments were created (same checks as test_controller_role_assignment_migration)
    for assignment in (
        ('controller-organization-admin', 'Organization Admin', 'controller-admin-organization'),
        ('controller-organization-member', 'Organization Member', 'controller-member-organization'),
        ('controller-team-admin', 'Team Admin', 'controller-admin-team'),
        ('controller-team-member', 'Team Member', 'controller-member-team'),
        ('controller-platform-auditor', 'Platform Auditor', None),
        ('controller-dummy-user', 'controller-dummy-role', 'controller-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])

    user_assignment_count_after_first_run = RoleUserAssignment.objects.count()
    team_assignment_count_after_first_run = RoleTeamAssignment.objects.count()
    assert user_assignment_count_after_first_run > 0

    # --- Second run: reinstall scenario ---
    # Reset the migration flag so the command doesn't short-circuit with
    # "Migration has already completed. Skipping."
    MigrateServiceDataHasRan.mark_migration_not_completed()

    # Clear captured output from the first run
    capsys.readouterr()

    call_command("migrate_service_data", username=admin_user.username)

    # No new assignments should have been created — the PK cursor is past
    # all existing assignments, so the API returns zero results.
    assert RoleUserAssignment.objects.count() == user_assignment_count_after_first_run
    assert RoleTeamAssignment.objects.count() == team_assignment_count_after_first_run

    # The command output should confirm zero assignments created
    captured = capsys.readouterr()
    assert "0 assignments created" in captured.out


@pytest.mark.django_db()
def test_controller_role_assignment_migration_paginated(migration_service_controller_roles_paginated, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated with pagination"""

    # migration_service_controller_roles_paginated creates 40 assignments and sets the page size low to force pagination
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 40


@pytest.mark.django_db()
def test_controller_role_assignment_migration_duplicate_team_names(
    migration_service_controller_roles_duplicate_teams, admin_user, admin_api_client, patched_resource_client
):
    """Test that role assignments in controller are migrated when duplicate team names exist"""

    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 2


@pytest.mark.django_db()
def test_controller_role_assignment_remoteobject(migration_service_controller_roles_remoteobject, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated when they reference remote objects"""
    assert RoleUserAssignment.objects.filter(user__username='test-user').count() == 0
    assert RoleTeamAssignment.objects.filter(team__name='test-team').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='test-user').count() == 1
    # Confirm that the migrated assignment's RoleDefinition references a RemoteObject
    rd = RoleUserAssignment.objects.get(user__username='test-user').role_definition
    assert issubclass(rd.content_type.model_class(), RemoteObject)


@pytest.mark.django_db()
def test_hub_role_assignment_migration(migration_service_hub_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in hub are migrated"""

    service_client = patched_resource_client(service=migration_service_hub_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    _assert_all_resources_synced(admin_api_client, migration_service_hub_roles, service_client)

    # For hub, team member should be migrated, as should the dummy role.
    for assignment in (
        ('hub-team-member', 'Team Member', 'hub-member-team'),
        ('hub-dummy-user', 'hub-dummy-role', 'hub-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])

    # Assert that other platform role assignments are not migrated from hub
    for assignment in (
        # We don't create these first two, so they should not be present
        ('hub-organization-admin', 'Organization Admin', 'hub-admin-organization'),
        ('hub-organization-member', 'Organization Member', 'hub-member-organization'),
        # We create Team Admin in the fixture but it should only be migrated from Controller.
        # Hub django migrations for 2.6 should be changing Team Admins to Team Members
        # before we migrate, but we still want to be sure that we're not elevating hub admin roles
        # to platform admin roles during migration
        ('hub-team-admin', 'Team Admin', 'hub-admin-team'),
    ):
        assert not _user_assignment_exists(assignment[0], assignment[1], assignment[2])


# Tests for role user assignment handling when objects don't exist in Gateway DB
@pytest.mark.django_db()
def test_role_assignment_migration_skips_user_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    # Mock successful migration
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        # Mock consistency check to avoid superuser validation issues
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
        # Generate UUID for a user that could not have been migrated and will not exist
        invalid_user_ansible_id = str(uuid.uuid4())
        # First call returns data for pagination, second call returns
        # empty for the post-run drift check.
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "next": None,
            "results": [
                {"id": 1, "object_ansible_id": None, "content_type": "", "role_definition": "Platform Auditor", "user_ansible_id": invalid_user_ansible_id}
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"results": [], "next": None}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Unable to find user with ansible_id {invalid_user_ansible_id}" in captured.err


@pytest.mark.django_db()
def test_role_assignment_migration_skips_role_definition_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    # Mock successful migration
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        # Mock consistency check to avoid superuser validation issues
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
        # Create a user so that the ansible_id matches
        test_user = User.objects.create(username='test-user')
        # First call returns data for pagination, second call returns
        # empty for the post-run drift check.
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "next": None,
            "results": [
                {
                    "id": 1,
                    "object_ansible_id": None,
                    "content_type": "",
                    "role_definition": "INVALID ROLE DEFINITION",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"results": [], "next": None}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert "Unable to find role definition 'INVALID ROLE DEFINITION'" in captured.err


@pytest.mark.django_db()
def test_role_assignment_migration_skips_object_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    # Mock successful migration
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        # Mock consistency check to avoid superuser validation issues
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {"count": 0, "results": []}
        # Generate UUID for an object that could not have been migrated
        invalid_object_ansible_id = str(uuid.uuid4())
        test_user = User.objects.create(username='test-user')
        # First call returns data for pagination, second call returns
        # empty for the post-run drift check.
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "next": None,
            "results": [
                {
                    "id": 1,
                    "object_ansible_id": invalid_object_ansible_id,
                    "content_type": "shared.team",
                    "role_definition": "Team Member",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"results": [], "next": None}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Unable to find content object with ansible_id {invalid_object_ansible_id}" in captured.err


# Parameterized tests for _ensure_controller_gateway_superusers method
@pytest.mark.parametrize(
    "gateway_users,controller_users,expected_promotions,expected_errors,expected_output",
    [
        # Test case: User exists in Gateway but needs promotion
        (
            [("controller_super_user", False)],  # (username, is_superuser)
            [("admin", True), ("controller_super_user", True)],  # Controller superusers
            ["controller_super_user"],  # Users that should be promoted
            [],  # No errors expected
            ["Promoted Gateway user 'controller_super_user' to superuser to match Controller status"],
        ),
        # Test case: User missing from Gateway (migration failure)
        (
            [],  # No users created in Gateway
            [("admin", True), ("missing_user", True)],  # Controller superusers
            [],  # No promotions
            ["missing_user"],  # Users that should trigger error
            ["Error: Users ['missing_user'] are superusers in Controller but don't exist in Gateway"],
        ),
        # Test case: Consistent superusers
        (
            [],  # Only admin exists (from fixture)
            [("admin", True)],  # Only admin is superuser in Controller
            [],  # No promotions needed
            [],  # No errors
            ["Controller and Gateway superusers are consistent"],
        ),
        # Test case: Mixed scenario - some promotion, some missing
        (
            [("needs_promotion", False)],  # User exists but not superuser
            [("admin", True), ("needs_promotion", True), ("missing_user", True)],
            ["needs_promotion"],  # This user should be promoted
            ["missing_user"],  # This user should trigger error
            [
                "Promoted Gateway user 'needs_promotion' to superuser to match Controller status",
                "Error: Users ['missing_user'] are superusers in Controller but don't exist in Gateway",
            ],
        ),
    ],
)
@pytest.mark.django_db
def test_ensure_controller_gateway_superusers_scenarios(
    gateway_users, controller_users, expected_promotions, expected_errors, expected_output, admin_user, capsys, service_api_route_controller
):
    """Parameterized test for _ensure_controller_gateway_superusers method scenarios"""

    # Setup Gateway users
    created_users = {}
    for username, is_superuser in gateway_users:
        created_users[username] = User.objects.create(username=username, is_superuser=is_superuser)

    gateway_superusers = {"admin"}  # admin is always superuser from fixture
    cmd = MigrateCommand()

    # Mock client with Controller superusers
    mock_client = Mock()

    # Mock list_resources response with resource_data included (bulk fetch)
    list_results = []

    for i, (username, is_superuser) in enumerate(controller_users):
        ansible_id = f"ansible-id-{i}"
        list_results.append({"ansible_id": ansible_id, "resource_data": {"username": username, "is_superuser": is_superuser}})

    mock_client.list_resources.return_value.json.return_value = {"count": len(controller_users), "results": list_results, "next": None}

    with patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient', return_value=mock_client):
        if expected_errors:
            # Test error scenarios
            from django.core.management.base import CommandError

            with pytest.raises(CommandError) as exc_info:
                cmd._ensure_controller_gateway_superusers(service_api_route_controller, gateway_superusers, admin_user)

            # Verify error message contains expected users
            error_message = str(exc_info.value)
            assert "Migration failure detected" in error_message
            for missing_user in expected_errors:
                assert missing_user in error_message

        else:
            # Test success scenarios
            cmd._ensure_controller_gateway_superusers(service_api_route_controller, gateway_superusers, admin_user)

        # Verify promotions happened
        for username in expected_promotions:
            user = created_users[username]
            user.refresh_from_db()
            assert user.is_superuser is True, f"User {username} should have been promoted to superuser"

        # Verify expected output messages
        captured = capsys.readouterr()
        output = captured.out + captured.err
        for expected_msg in expected_output:
            assert expected_msg in output, f"Expected message '{expected_msg}' not found in output"


# =============================================================================
# Tests for _collect_controller_superusers helper function
# =============================================================================


@pytest.fixture
def mock_controller_client(service_api_route_controller):
    """Mock GWResourceAPIClient for _collect_controller_superusers tests.

    Yields (mock_client, run) where run(page_data, resource_data, user) calls
    _collect_controller_superusers with the mock wired up.
    page_data: dict mapping page number -> {"results": [...], "next": ...}
    resource_data: dict mapping ansible_id -> detail response dict
    """
    mock_client = Mock()

    def run(page_data, resource_data, admin_user):
        def mock_list_resources(filters=None):
            page = filters["page"]
            response = page_data[page].copy()
            # Merge resource_data into list results so the bulk-fetch path works
            response["results"] = [{**item, **resource_data.get(item["ansible_id"], {})} for item in response["results"]]
            mock_response = Mock()
            mock_response.json.return_value = response
            return mock_response

        mock_client.list_resources.side_effect = mock_list_resources

        cmd = MigrateCommand()
        with patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient', return_value=mock_client):
            return cmd._collect_controller_superusers(service_api_route_controller, admin_user)

    yield mock_client, run


@pytest.mark.django_db
def test_collect_controller_superusers_single_page(admin_user, mock_controller_client):
    """Test _collect_controller_superusers returns superuser usernames from a single page of results."""
    mock_client, run = mock_controller_client

    page_data = {
        1: {"results": [{"ansible_id": "id-1"}, {"ansible_id": "id-2"}, {"ansible_id": "id-3"}], "next": None},
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
    """Test _collect_controller_superusers handles paginated API responses correctly."""
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
    mock_client.list_resources.assert_any_call(filters={"content_type__resource_type__name": "shared.user", "extra_fields": "resource_data", "page": 1})
    mock_client.list_resources.assert_any_call(filters={"content_type__resource_type__name": "shared.user", "extra_fields": "resource_data", "page": 2})
    assert mock_client.list_resources.call_count == 2


@pytest.mark.django_db
def test_collect_controller_superusers_no_superusers(admin_user, mock_controller_client):
    """Test _collect_controller_superusers returns empty set when no superusers exist."""
    _, run = mock_controller_client

    page_data = {
        1: {"results": [{"ansible_id": "id-1"}, {"ansible_id": "id-2"}], "next": None},
    }
    resource_data = {
        "id-1": {"resource_data": {"username": "user1", "is_superuser": False}},
        "id-2": {"resource_data": {"username": "user2", "is_superuser": False}},
    }

    result = run(page_data, resource_data, admin_user)

    assert result == set()


@pytest.mark.django_db
def test_collect_controller_superusers_empty_results(admin_user, mock_controller_client):
    """Test _collect_controller_superusers handles empty results."""
    _, run = mock_controller_client

    page_data = {
        1: {"results": [], "next": None},
    }

    result = run(page_data, {}, admin_user)

    assert result == set()


# =============================================================================
# Tests for _demote_extra_superusers pagination
# =============================================================================


@pytest.mark.django_db
def test_demote_extra_superusers_pagination(admin_user, service_api_route_hub, capsys):
    """Test _demote_extra_superusers handles paginated results and demotes correctly."""
    cmd = MigrateCommand()
    mock_client = Mock()

    page_data = {
        1: {
            "results": [
                {"ansible_id": "id-1", "resource_data": {"username": "extra_super", "is_superuser": True}},
            ],
            "next": "http://example.com/page=2",
        },
        2: {
            "results": [
                {"ansible_id": "id-2", "resource_data": {"username": "normal_user", "is_superuser": False}},
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

    with patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient', return_value=mock_client):
        cmd._demote_extra_superusers(service_api_route_hub, gateway_superusers, admin_user)

    mock_client.update_resource.assert_called_once()
    assert mock_client.list_resources.call_count == 2

    captured = capsys.readouterr()
    assert "Demoted user 'extra_super'" in captured.out


# =============================================================================
# Tests for _get_gateway_user helper function
# =============================================================================


@pytest.mark.django_db
def test_get_gateway_user_existing_user():
    """Test _get_gateway_user returns the user when it exists."""
    # Create a test user
    test_user = User.objects.create(username="existing_user")

    cmd = MigrateCommand()
    result = cmd._get_gateway_user("existing_user")

    # Verify the correct user is returned
    assert result == test_user
    assert result.username == "existing_user"


@pytest.mark.django_db
def test_get_gateway_user_nonexistent_user():
    """Test _get_gateway_user returns None when user doesn't exist."""
    cmd = MigrateCommand()
    result = cmd._get_gateway_user("nonexistent_user")

    # Verify None is returned for non-existent user
    assert result is None


# =============================================================================
# Tests for _sync_controller_superuser helper function
# =============================================================================


@pytest.mark.django_db
def test_sync_controller_superuser_promotes_existing_user(capsys):
    """Test _sync_controller_superuser promotes existing non-superuser to superuser."""
    # Create an existing Gateway user who is not a superuser
    gateway_user = User.objects.create(username="controller_admin", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "controller_admin", upstream_is_superuser=True)

    # Verify the gateway user was promoted
    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is True

    # Verify upstream_resource was updated
    assert upstream_resource["resource_data"]["is_superuser"] is True

    # Verify log output
    captured = capsys.readouterr()
    assert "Promoted Gateway user 'controller_admin' to superuser based on Controller" in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_new_user_logs_creation(capsys):
    """Test _sync_controller_superuser logs message for new user that will be created."""
    # No Gateway user exists yet
    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "new_controller_admin", upstream_is_superuser=True)

    # Verify upstream_resource was updated (user will be created later with superuser status)
    assert upstream_resource["resource_data"]["is_superuser"] is True

    # Verify log output
    captured = capsys.readouterr()
    assert "New user 'new_controller_admin' will be created with superuser status from Controller" in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_skips_non_superuser(capsys):
    """Test _sync_controller_superuser does nothing when upstream user is not superuser."""
    # Create an existing Gateway user
    gateway_user = User.objects.create(username="regular_user", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "regular_user", upstream_is_superuser=False)

    # Verify the gateway user was NOT promoted
    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is False

    # Verify upstream_resource was NOT changed
    assert upstream_resource["resource_data"]["is_superuser"] is False

    # Verify no promotion log
    captured = capsys.readouterr()
    assert "Promoted" not in captured.out


@pytest.mark.django_db
def test_sync_controller_superuser_already_superuser(capsys):
    """Test _sync_controller_superuser doesn't re-promote already superuser."""
    # Create an existing Gateway user who is already a superuser
    gateway_user = User.objects.create(username="existing_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_controller_superuser(upstream_resource, "existing_admin", upstream_is_superuser=True)

    # Verify the gateway user is still a superuser
    gateway_user.refresh_from_db()
    assert gateway_user.is_superuser is True

    # Verify upstream_resource still has is_superuser=True
    assert upstream_resource["resource_data"]["is_superuser"] is True

    # Verify no "Promoted" log (already superuser)
    captured = capsys.readouterr()
    assert "Promoted" not in captured.out


# =============================================================================
# Tests for _sync_hub_eda_superuser helper function
# =============================================================================


@pytest.mark.django_db
def test_sync_hub_eda_superuser_gateway_superuser(capsys):
    """Test _sync_hub_eda_superuser sets is_superuser=True when Gateway user is superuser."""
    # Create a Gateway superuser
    User.objects.create(username="hub_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": False}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "hub_admin", upstream_is_superuser=False, service_type="hub")

    # Verify upstream_resource was updated to match Gateway
    assert upstream_resource["resource_data"]["is_superuser"] is True

    # Verify log output shows promotion
    captured = capsys.readouterr()
    assert "Gateway user is superuser: True" in captured.out
    assert "promoted to superuser in hub" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_demotes_non_gateway_superuser(capsys):
    """Test _sync_hub_eda_superuser demotes Hub/EDA superuser when Gateway user is not superuser."""
    # Create a non-superuser Gateway user
    User.objects.create(username="hub_regular", is_superuser=False)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "hub_regular", upstream_is_superuser=True, service_type="hub")

    # Verify upstream_resource was updated to match Gateway (demoted)
    assert upstream_resource["resource_data"]["is_superuser"] is False

    # Verify log output shows demotion
    captured = capsys.readouterr()
    assert "Gateway user is superuser: False" in captured.out
    assert "demoted from superuser in hub" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_no_gateway_user(capsys):
    """Test _sync_hub_eda_superuser sets is_superuser=False when Gateway user doesn't exist."""
    # No Gateway user exists
    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "missing_user", upstream_is_superuser=True, service_type="eda")

    # Verify upstream_resource was set to False (no Gateway user = not superuser)
    assert upstream_resource["resource_data"]["is_superuser"] is False

    # Verify log output
    captured = capsys.readouterr()
    assert "Gateway user does not exist, will not be superuser" in captured.out
    assert "demoted from superuser in eda" in captured.out


@pytest.mark.django_db
def test_sync_hub_eda_superuser_no_change_needed(capsys):
    """Test _sync_hub_eda_superuser logs no change when status already matches."""
    # Create a Gateway superuser
    User.objects.create(username="synced_admin", is_superuser=True)

    upstream_resource = {"resource_data": {"is_superuser": True}}

    cmd = MigrateCommand()
    cmd._sync_hub_eda_superuser(upstream_resource, "synced_admin", upstream_is_superuser=True, service_type="hub")

    # Verify upstream_resource stays True
    assert upstream_resource["resource_data"]["is_superuser"] is True

    # Verify no promotion/demotion log (status already matches)
    captured = capsys.readouterr()
    assert "promoted to" not in captured.out
    assert "demoted from" not in captured.out


# =============================================================================
# Tests for _log_progress (AAP-76816)
# =============================================================================


def test_log_progress_emits_at_thresholds(caplog):
    """Test that progress is logged at 5% threshold crossings."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger="aap.gateway.management.commands.migrate_service_data"):
        for i in range(1, 101):
            cmd._log_progress("test", i, 100)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [test]" in msg]
    assert len(progress_msgs) == 21  # 0% + 5% through 100%
    assert "(0%)" in progress_msgs[0]
    assert "(100%)" in progress_msgs[-1]


def test_log_progress_zero_items(caplog):
    """Test that zero items logs a single message."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger="aap.gateway.management.commands.migrate_service_data"):
        cmd._log_progress("empty", 0, 0)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [empty]" in msg]
    assert len(progress_msgs) == 1
    assert "0 items to process" in progress_msgs[0]


def test_log_progress_small_count_skips_intermediate(caplog):
    """Test that small counts skip intermediate thresholds."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger="aap.gateway.management.commands.migrate_service_data"):
        for i in range(1, 11):
            cmd._log_progress("small", i, 10)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [small]" in msg]
    assert not any("(5%)" in msg for msg in progress_msgs)
    assert any("(10%)" in msg for msg in progress_msgs)


def test_log_progress_bookends_always_logged(caplog):
    """Test that first and last items always generate log output."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger="aap.gateway.management.commands.migrate_service_data"):
        cmd._log_progress("bookend", 1, 7)
        cmd._log_progress("bookend", 7, 7)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [bookend]" in msg]
    assert len(progress_msgs) >= 2
    assert "1/7" in progress_msgs[0]
    assert "7/7" in progress_msgs[-1]
    assert "(100%)" in progress_msgs[-1]


def test_log_progress_no_duplicate_100(caplog):
    """Test that 100% is not logged twice when last item lands exactly on a threshold."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger="aap.gateway.management.commands.migrate_service_data"):
        for i in range(1, 21):
            cmd._log_progress("exact", i, 20)

    progress_msgs = [msg for msg in caplog.messages if "(100%)" in msg and "exact" in msg]
    assert len(progress_msgs) == 1


# =============================================================================
# Tests for _configure_logging and _log (AAP-76816)
# =============================================================================

MIGRATE_LOGGER_NAME = "aap.gateway.management.commands.migrate_service_data"


@pytest.fixture(autouse=True)
def _restore_migrate_logger_state():
    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    original_handlers = migrate_logger.handlers[:]
    original_level = migrate_logger.level
    original_propagate = migrate_logger.propagate
    try:
        yield
    finally:
        for handler in migrate_logger.handlers[:]:
            handler.close()
        migrate_logger.handlers = original_handlers
        migrate_logger.setLevel(original_level)
        migrate_logger.propagate = original_propagate


def test_configure_logging_with_log_file(tmp_path):
    """When --log-file is provided, logger gets a StreamHandler at INFO."""
    cmd = MigrateCommand()
    log_file = tmp_path / "test.log"

    cmd._configure_logging(str(log_file))

    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    assert len(migrate_logger.handlers) == 1
    assert isinstance(migrate_logger.handlers[0], logging.StreamHandler)
    assert migrate_logger.level <= logging.INFO
    assert not migrate_logger.propagate

    cmd._log_file_handle.close()


def test_configure_logging_without_log_file():
    """When --log-file is omitted, logger gets a NullHandler."""
    cmd = MigrateCommand()

    cmd._configure_logging(None)

    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    assert len(migrate_logger.handlers) == 1
    assert isinstance(migrate_logger.handlers[0], logging.NullHandler)
    assert not migrate_logger.propagate


def test_configure_logging_closes_previous_file_handle(tmp_path):
    """Calling _configure_logging twice closes the previous file handle."""
    cmd = MigrateCommand()
    first_log = tmp_path / "first.log"
    second_log = tmp_path / "second.log"

    cmd._configure_logging(str(first_log))
    first_handle = cmd._log_file_handle
    assert not first_handle.closed

    cmd._configure_logging(str(second_log))
    assert first_handle.closed
    assert not cmd._log_file_handle.closed

    cmd._log_file_handle.close()


def test_configure_logging_respects_lower_level(tmp_path):
    """If the logger is already at DEBUG, _configure_logging should not raise it to INFO."""
    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    migrate_logger.setLevel(logging.DEBUG)

    cmd = MigrateCommand()
    cmd._configure_logging(str(tmp_path / "test.log"))

    assert migrate_logger.level == logging.DEBUG

    cmd._log_file_handle.close()


def test_configure_logging_inherits_formatter(tmp_path):
    """When the aap logger has a console handler with a formatter, it should be reused."""
    aap_logger = logging.getLogger("aap")
    original_handlers = aap_logger.handlers[:]
    test_formatter = logging.Formatter("TEST %(message)s")
    test_handler = logging.StreamHandler()
    test_handler.setFormatter(test_formatter)
    aap_logger.handlers = [test_handler]

    try:
        cmd = MigrateCommand()
        cmd._configure_logging(str(tmp_path / "test.log"))

        migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
        assert migrate_logger.handlers[0].formatter is test_formatter
        cmd._log_file_handle.close()
    finally:
        aap_logger.handlers = original_handlers


def test_log_info_writes_to_stdout(caplog):
    """_log at INFO writes to stdout and the logger."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("test info message", logging.INFO)

    assert "test info message" in cmd.stdout.getvalue()
    assert "test info message" in caplog.messages


def test_log_warning_writes_to_stderr(caplog):
    """_log at WARNING writes to stderr and the logger."""
    cmd = MigrateCommand()
    cmd.stderr = StringIO()

    with caplog.at_level("WARNING", logger=MIGRATE_LOGGER_NAME):
        cmd._log("test warning message", logging.WARNING)

    assert "test warning message" in cmd.stderr.getvalue()
    assert "test warning message" in caplog.messages


def test_log_writes_to_log_file(tmp_path):
    """_log writes structured output to --log-file."""
    cmd = MigrateCommand()
    log_file = tmp_path / "test.log"

    cmd._configure_logging(str(log_file))
    cmd._log("file output test", logging.INFO)
    cmd._log_file_handle.flush()

    content = log_file.read_text()
    assert "file output test" in content
    assert "INFO" in content

    cmd._log_file_handle.close()


def test_log_file_not_written_without_flag(tmp_path, caplog):
    """Without --log-file, logger messages go to NullHandler only."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd._configure_logging(None)

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("null handler test", logging.INFO)

    assert "null handler test" in cmd.stdout.getvalue()
    assert "null handler test" not in caplog.messages


def test_log_splits_newlines_for_logger(caplog):
    """_log splits messages on newlines so each line gets a formatter prefix."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("\n=== Section Header ===", logging.INFO)

    assert "\n=== Section Header ===" in cmd.stdout.getvalue()
    assert "=== Section Header ===" in caplog.messages
    assert "" not in caplog.messages


def test_log_splits_multiline_message(caplog):
    """Multi-line messages produce one log record per non-empty line."""
    cmd = MigrateCommand()
    cmd.stderr = StringIO()

    with caplog.at_level("WARNING", logger=MIGRATE_LOGGER_NAME):
        cmd._log("line one\nline two\n\nline four", logging.WARNING)

    assert "line one" in caplog.messages
    assert "line two" in caplog.messages
    assert "line four" in caplog.messages
    assert len([m for m in caplog.messages if m in ("line one", "line two", "line four")]) == 3


def test_copy_console_handler_config_no_aap_handlers(tmp_path):
    """When the aap logger has no handlers, _copy_console_handler_config is a no-op."""
    aap_logger = logging.getLogger("aap")
    original_handlers = aap_logger.handlers[:]
    aap_logger.handlers = []

    try:
        cmd = MigrateCommand()
        cmd._configure_logging(str(tmp_path / "test.log"))

        migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
        assert migrate_logger.handlers[0].formatter is None
        assert migrate_logger.handlers[0].filters == []
        cmd._log_file_handle.close()
    finally:
        aap_logger.handlers = original_handlers


@pytest.mark.django_db
def test_reconcile_existing_resource_matching_ansible_id_same_data():
    """Case 1 with matching data: logs 'Correcting service_id'."""
    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    resource_type = ResourceType.objects.get(name="shared.organization")
    org = Organization.objects.create(name="reconcile-org")
    resource = Resource.objects.get(content_type=resource_type.content_type, object_id=org.pk)
    local_data = resource_type.serializer_class(org).data

    resource_context = {
        "type": resource_type,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }
    upstream_resource = {
        "ansible_id": str(resource.ansible_id),
        "name": org.name,
        "resource_data": local_data,
    }
    updated_service_resource = {}

    result = cmd._reconcile_existing_resource(upstream_resource, resource_context, local_data, updated_service_resource)

    assert result is False
    assert "Correcting service_id" in cmd.stdout.getvalue()


@pytest.mark.django_db
def test_reconcile_existing_resource_matching_ansible_id_different_data():
    """Case 1 with different data: logs 'Updating already-merged' and overwrites resource_data."""
    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    resource_type = ResourceType.objects.get(name="shared.organization")
    org = Organization.objects.create(name="reconcile-org-diff")
    resource = Resource.objects.get(content_type=resource_type.content_type, object_id=org.pk)
    local_data = resource_type.serializer_class(org).data

    resource_context = {
        "type": resource_type,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }
    upstream_resource = {
        "ansible_id": str(resource.ansible_id),
        "name": org.name,
        "resource_data": {**local_data, "description": "stale upstream copy"},
    }
    updated_service_resource = {}

    result = cmd._reconcile_existing_resource(upstream_resource, resource_context, local_data, updated_service_resource)

    assert result is False
    assert updated_service_resource["resource_data"] == local_data
    combined_output = cmd.stdout.getvalue() + cmd.stderr.getvalue()
    assert "Updating already-merged" in combined_output


# =============================================================================
# Tests for _migrate_single_service error paths (coverage)
# =============================================================================


@pytest.mark.django_db
def test_migrate_single_service_skips_unknown_service_type(admin_user, capsys, service_api_route_controller):
    """When service metadata reports an unknown service_type, the service is skipped with a warning."""
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

    with patch("aap_gateway_api.management.commands.migrate_service_data.resources_client.GWResourceAPIClient", return_value=mock_client):
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

    with patch("aap_gateway_api.management.commands.migrate_service_data.resources_client.GWResourceAPIClient", return_value=mock_client):
        success, error = cmd._migrate_single_service(service_api_route_controller, service_api_route_controller.api_slug, admin_user)

    assert success is False
    captured = capsys.readouterr()
    assert "Skipping service" in captured.err
    assert "Service type mismatch" in captured.err


# =============================================================================
# Tests for _merge_partially_migrated_users and _merge_user_group (coverage)
# =============================================================================


@pytest.mark.django_db
def test_merge_partially_migrated_users_with_users(admin_user, capsys, service_api_route_controller):
    """Exercise the partially migrated user merge flow with actual users."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    controller_service_id = uuid.uuid4()
    service_api_route_controller.service_cluster.service_id = controller_service_id
    service_api_route_controller.service_cluster.save()

    user1 = User.objects.create(username="controller_testmerge1")
    resource1 = user1.resource
    resource1.service_id = controller_service_id
    resource1.is_partially_migrated = True
    resource1.save()

    cmd._merge_partially_migrated_users([service_api_route_controller], admin_user)

    captured = capsys.readouterr()
    assert "Grouping users by their service types" in captured.out
    assert "Correlating users across services" in captured.out
    assert "user groups to merge" in captured.out
    assert "Merging" in captured.out
    assert "Completed merging" in captured.out


@pytest.mark.django_db
def test_merge_user_group_with_conflicts(capsys):
    """When users can't be merged due to conflicts, warnings are logged."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    user1 = User.objects.create(username="main_user", email="main@example.com")
    user2 = User.objects.create(username="other_user", email="other@example.com")

    user_accounts = [
        ("controller", user1, "main_user"),
        ("hub", user2, "other_user"),
    ]

    with patch("aap_gateway_api.management.commands.migrate_service_data.can_accounts_be_merged", return_value=False):
        result = cmd._merge_user_group("main_user", user_accounts)

    assert result == 0
    captured = capsys.readouterr()
    assert "Merging user group for" in captured.out
    assert "Using controller user" in captured.out
    assert "Cannot merge user group" in captured.err
    assert "conflicts detected" in captured.err


@pytest.mark.django_db
def test_merge_user_group_successful(capsys):
    """When users can be merged, the merge proceeds and logs progress."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    user1 = User.objects.create(username="main_user2")
    user2 = User.objects.create(username="other_user2")

    user_accounts = [
        ("controller", user1, "main_user2"),
        ("hub", user2, "other_user2"),
    ]

    with (
        patch("aap_gateway_api.management.commands.migrate_service_data.can_accounts_be_merged", return_value=True),
        patch("aap_gateway_api.management.commands.migrate_service_data.link_account"),
        patch("aap_gateway_api.management.commands.migrate_service_data.migrate_account"),
    ):
        result = cmd._merge_user_group("main_user2", user_accounts)

    assert result == 2
    captured = capsys.readouterr()
    assert "Merging hub user" in captured.out
    assert "Successfully merged hub user" in captured.out
    assert "Migrating main user" in captured.out
    assert "Successfully migrated main user" in captured.out
