import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleUserAssignment
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.core.management import call_command
from django.db import IntegrityError

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import MigratedUserMetadata, Organization, Route, Team, User
from aap_gateway_api.tests.service_test_app.launch import launch_service

SEP_CHAR = "_"

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


def _launch_service(svc_route: Route, fixture: str, svc_type: str = "awx"):
    port = svc_route.service_port
    key = svc_route.service_cluster.generate_key()
    return launch_service(service_type=svc_type, port=port, setup_fixture=fixture, secret_key=key.secret)


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


@pytest.fixture
def migration_service(patched_resource_client, service_api_route_controller):
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_invalid_users(patched_resource_client, service_api_route_controller):
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
                mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}
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
        mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}
        mock_client_class.return_value = mock_client

        # Should successfully process the single service
        call_command("migrate_service_data", username=admin_user.username)

        # Check that only the controller service was processed
        captured = capsys.readouterr()
        assert "Found 1 services to migrate" in captured.out
        assert f"Processing service: {service_api_route_controller.api_slug}" in captured.out
        assert "hub" not in captured.out  # Hub should not be processed
        assert "eda" not in captured.out  # EDA should not be processed
        assert "Successful migrations: 1" in captured.out
        assert "Failed migrations: 0" in captured.out
        assert "All services migration completed successfully!" in captured.out


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
    assert any(
        keyword in error_message for keyword in ["duplicate", "unique", "constraint", "already exists"]
    ), f"Expected error message to indicate constraint violation, got: {exc_info.value}"

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
        name="Legacy Controller Admin", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
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
        name="Legacy SSO", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
    )
    # Use update() to bypass the model's save method validation
    Authenticator.objects.filter(id=legacy_auth1.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth1.refresh_from_db()

    legacy_auth2 = Authenticator.objects.create(
        name="Legacy Password", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
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
        name="Unused Legacy Auth", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
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
        name="Legacy Auth", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
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
        name="Legacy Controller Admin", type="ansible_base.authentication.authenticator_plugins.ldap", enabled=True, configuration={}  # Valid type for creation
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
        mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}
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
def migration_service_controller_user_roles_paginated(patched_resource_client, service_api_route_controller):
    """Launch a controller service with controller-specific user role assignment test data that requires pagination"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_user_roles_pagination")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_controller_user_roles(patched_resource_client, service_api_route_controller):
    """Launch a controller service with controller-specific user role assignment test data"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_user_roles")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_controller_user_roles_duplicate_teams(patched_resource_client, service_api_route_controller):
    """Launch a controller service with controller-specific user role assignment test data across duplicate team names"""
    proc = _launch_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_user_roles_duplicate_teams")
    yield service_api_route_controller
    _kill_service(proc)


@pytest.fixture
def migration_service_hub_user_roles(patched_resource_client, service_api_route_hub):
    """Launch a hub service with hub-specific user role assignment test data"""
    proc = _launch_service(svc_route=service_api_route_hub, fixture="migration_tests_hub_user_roles", svc_type="galaxy")
    yield service_api_route_hub
    _kill_service(proc)


def _assignment_exists(username, role_definition_name, object_name) -> bool:
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
def test_controller_user_role_assignment_migration(migration_service_controller_user_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated"""

    # migration_service_controller_user_roles creates users in controller with org admin, org member, team admin, team member
    service_client = patched_resource_client(service=migration_service_controller_user_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    _assert_all_resources_synced(admin_api_client, migration_service_controller_user_roles, service_client)

    for assignment in (
        ('controller-organization-admin', 'Organization Admin', 'controller-admin-organization'),
        ('controller-organization-member', 'Organization Member', 'controller-member-organization'),
        ('controller-team-admin', 'Team Admin', 'controller-admin-team'),
        ('controller-team-member', 'Team Member', 'controller-member-team'),
        ('controller-platform-auditor', 'Platform Auditor', None),
    ):
        assert _assignment_exists(assignment[0], assignment[1], assignment[2])

    # Assert that other role assignments are not migrated
    for assignment in (('controller-dummy-user', 'role-no-migrate', 'controller-dummy-organization'),):
        assert not _assignment_exists(assignment[0], assignment[1], assignment[2])


@pytest.mark.django_db()
def test_controller_user_role_assignment_migration_paginated(
    migration_service_controller_user_roles_paginated, admin_user, admin_api_client, patched_resource_client
):
    """Test that role assignments in controller are migrated with pagination"""

    # migration_service_controller_user_roles creates users in controller with org admin, org member, team admin, team member
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 40


@pytest.mark.django_db()
def test_controller_user_role_assignment_migration_duplicate_team_names(
    migration_service_controller_user_roles_duplicate_teams, admin_user, admin_api_client, patched_resource_client
):
    """Test that role assignments in controller are migrated when duplicate team names exist"""

    # migration_service_controller_user_roles creates users in controller with org admin, org member, team admin, team member
    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    # Check that these apply to both teams, maybe member for one and admin for the other?
    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 2


@pytest.mark.django_db()
def test_hub_user_role_assignment_migration(migration_service_hub_user_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in hub are migrated"""

    # migration_service_controller_user_roles creates users in controller with org admin, org member, team admin, team member
    service_client = patched_resource_client(service=migration_service_hub_user_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    _assert_all_resources_synced(admin_api_client, migration_service_hub_user_roles, service_client)

    # For hub, only team member should be migrated
    for assignment in (('hub-team-member', 'Team Member', 'hub-member-team'),):
        assert _assignment_exists(assignment[0], assignment[1], assignment[2])

    # Assert that other role assignments are not migrated from hub
    for assignment in (
        ('hub-organization-admin', 'Organization Admin', 'hub-admin-organization'),
        ('hub-organization-member', 'Organization Member', 'hub-member-organization'),
        ('hub-team-admin', 'Team Admin', 'hub-admin-team'),
        ('hub-dummy-user', 'role-no-migrate', 'hub-dummy-organization'),
    ):
        assert not _assignment_exists(assignment[0], assignment[1], assignment[2])


# Tests for role user assignment handling when objects don't exist in Gateway DB
@pytest.mark.django_db()
def test_user_role_assignment_migration_skips_user_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
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
        mock_client.list_user_assignments.return_value.json.return_value = {
            "count": 0,
            "results": [{"object_ansible_id": None, "content_type": None, "role_definition": "Platform Auditor", "user_ansible_id": invalid_user_ansible_id}],
        }
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Unable to find gateway user with ansible_id {invalid_user_ansible_id}" in captured.err


@pytest.mark.django_db()
def test_user_role_assignment_migration_skips_role_definition_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
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
        mock_client.list_user_assignments.return_value.json.return_value = {
            "count": 0,
            "results": [
                {
                    "object_ansible_id": None,
                    "content_type": None,
                    "role_definition": "INVALID ROLE DEFINITION",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert "Warning: Unable to find role definition INVALID ROLE DEFINITION, skipping assignment" in captured.err


@pytest.mark.django_db()
def test_user_role_assignment_migration_skips_object_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
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
        mock_client.list_user_assignments.return_value.json.return_value = {
            "count": 0,
            "results": [
                {
                    "object_ansible_id": invalid_object_ansible_id,
                    "content_type": "shared.team",
                    "role_definition": "Team Member",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        # It should not have migrated any assignments
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Warning: Unable to find object of type shared.team with ansible_id {invalid_object_ansible_id}, skipping assignment" in captured.err


# Tests for use_controller_password flag functionality
@pytest.mark.django_db(transaction=True)
def test_set_use_controller_password_flag_existing_user(capsys):
    """Test that _set_use_controller_password_flag sets the flag on existing users"""

    # Create a user without the flag set
    test_user = User.objects.create(username="test_user", use_controller_password=False)
    assert test_user.use_controller_password is False

    # Create upstream resource data
    upstream_resource = {
        "resource_data": {
            "username": "test_user",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }
    }

    cmd = MigrateCommand()
    result = cmd._set_use_controller_password_flag(upstream_resource)

    # Verify the flag was set
    test_user.refresh_from_db()
    assert test_user.use_controller_password is True

    # Verify return value
    assert result == upstream_resource

    # Verify logging
    captured = capsys.readouterr()
    assert "Set use_controller_password flag for Gateway user 'test_user'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_set_use_controller_password_flag_nonexistent_user(capsys):
    """Test that _set_use_controller_password_flag handles nonexistent users gracefully"""

    # Create upstream resource data for non-existent user
    upstream_resource = {
        "resource_data": {
            "username": "nonexistent_user",
            "email": "nonexistent@example.com",
            "first_name": "Non",
            "last_name": "Existent",
        }
    }

    cmd = MigrateCommand()
    result = cmd._set_use_controller_password_flag(upstream_resource)

    # Verify no user was created
    assert not User.objects.filter(username="nonexistent_user").exists()

    # Verify return value
    assert result == upstream_resource

    # Verify logging
    captured = capsys.readouterr()
    assert "Gateway user 'nonexistent_user' was not updated with 'use_controller_password' flag" in captured.out


@pytest.mark.django_db(transaction=True)
def test_use_controller_password_flag_integration_with_migration(admin_user, capsys, service_api_route_controller):
    """Test integration of use_controller_password flag setting during full migration"""

    # Mock the resource client for controller
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._merge_partially_migrated_users') as mock_merge_users,
    ):
        # Mock JWT and key creation
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None
        mock_merge_users.return_value = None

        mock_client = Mock()
        _setup_basic_service_client_mocks(mock_client, service_api_route_controller, admin_user)

        # Mock a user resource to be migrated
        mock_user_resource = {
            "ansible_id": str(uuid.uuid4()),
            "name": "controller_user",
            "resource_data": {
                "username": "controller_user",
                "email": "controller@example.com",
                "first_name": "Controller",
                "last_name": "User",
                "is_superuser": False,
            },
            "resource_type": "shared.user",
        }

        # Mock the API responses with call counter to simulate resource processing
        # Migration processes orgs, teams, then users - we need to mock all of them
        call_counts = {"shared.organization": 0, "shared.team": 0, "shared.user": 0}

        def mock_list_resources_response(*args, **kwargs):
            filters = kwargs.get('filters', {})
            resource_type = filters.get('content_type__resource_type__name')

            if resource_type == 'shared.user':
                call_counts['shared.user'] += 1
                if call_counts['shared.user'] == 1:
                    return Mock(json=lambda: {"count": 1, "results": [mock_user_resource]})
                else:
                    return Mock(json=lambda: {"count": 0, "results": []})
            else:
                # For organizations and teams, return empty immediately
                return Mock(json=lambda: {"count": 0, "results": []})

        mock_client.list_resources.side_effect = mock_list_resources_response
        mock_client.get_resource.return_value.json.return_value = mock_user_resource
        mock_client.update_resource.return_value = Mock()
        mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}

        mock_client_class.return_value = mock_client

        # Run migration
        call_command("migrate_service_data", username=admin_user.username)

        # Verify that the user was created with use_controller_password=True
        assert User.objects.filter(username="controller_user").exists()
        controller_user = User.objects.get(username="controller_user")
        assert controller_user.use_controller_password is True

        # Verify logging
        captured = capsys.readouterr()
        assert "Set use_controller_password flag for Gateway user 'controller_user'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_use_controller_password_flag_only_for_user_resources(admin_user, service_api_route_controller):
    """Test that use_controller_password flag is only set for user resources, not organizations or teams"""

    # Mock the resource client for controller
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._merge_partially_migrated_users') as mock_merge_users,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._set_use_controller_password_flag') as mock_set_flag,
    ):
        # Mock JWT and key creation
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None
        mock_merge_users.return_value = None

        mock_client = Mock()
        _setup_basic_service_client_mocks(mock_client, service_api_route_controller, admin_user)

        # Mock organization and user resources
        mock_org_resource = {
            "ansible_id": str(uuid.uuid4()),
            "name": "test_org",
            "resource_data": {"name": "test_org"},
            "resource_type": "shared.organization",
        }

        mock_user_resource = {
            "ansible_id": str(uuid.uuid4()),
            "name": "test_user",
            "resource_data": {
                "username": "test_user",
                "email": "user@example.com",
                "first_name": "Test",
                "last_name": "User",
                "is_superuser": False,
            },
            "resource_type": "shared.user",
        }

        # Mock multiple list_resources calls for different resource types
        # Use a call counter to simulate resources being processed and disappearing from subsequent queries
        call_counts = {"shared.organization": 0, "shared.user": 0}

        def mock_list_resources(*args, **kwargs):
            filters = kwargs.get('filters', {})
            resource_type = filters.get('content_type__resource_type__name')

            if resource_type == 'shared.organization':
                call_counts["shared.organization"] += 1
                if call_counts["shared.organization"] == 1:
                    return Mock(json=lambda: {"count": 1, "results": [mock_org_resource]})
                else:
                    return Mock(json=lambda: {"count": 0, "results": []})
            elif resource_type == 'shared.user':
                call_counts["shared.user"] += 1
                if call_counts["shared.user"] == 1:
                    return Mock(json=lambda: {"count": 1, "results": [mock_user_resource]})
                else:
                    return Mock(json=lambda: {"count": 0, "results": []})
            else:
                return Mock(json=lambda: {"count": 0, "results": []})

        mock_client.list_resources.side_effect = mock_list_resources

        def mock_get_resource(ansible_id):
            if ansible_id == mock_org_resource["ansible_id"]:
                return Mock(json=lambda: mock_org_resource)
            elif ansible_id == mock_user_resource["ansible_id"]:
                return Mock(json=lambda: mock_user_resource)
            return Mock(json=lambda: {})

        mock_client.get_resource.side_effect = mock_get_resource
        mock_client.update_resource.return_value = Mock()
        mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}

        mock_client_class.return_value = mock_client

        # Run migration
        call_command("migrate_service_data", username=admin_user.username)

        # Verify _set_use_controller_password_flag was called only for user resources
        # It should be called once for the user resource, not for the organization
        assert mock_set_flag.call_count == 1

        # Verify it was called with the user resource
        call_args = mock_set_flag.call_args[0][0]  # First argument of the first call
        assert call_args["resource_data"]["username"] == "test_user"


@pytest.mark.django_db(transaction=True)
def test_use_controller_password_flag_not_set_for_existing_users_during_merge(admin_user, service_api_route_controller):
    """Test that use_controller_password flag handling works correctly when merging with existing users"""
    # Create an existing user in Gateway (simulating a conflict scenario)
    existing_user = User.objects.create(username="existing_user", use_controller_password=False)

    # Mock the resource client for controller
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._merge_partially_migrated_users') as mock_merge_users,
    ):
        # Mock JWT and key creation
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None
        mock_merge_users.return_value = None

        mock_client = Mock()
        _setup_basic_service_client_mocks(mock_client, service_api_route_controller, admin_user)

        # Mock a user resource that will conflict with existing user
        mock_user_resource = {
            "ansible_id": existing_user.resource.ansible_id,  # Same ansible_id as existing user
            "name": "existing_user",
            "resource_data": {
                "username": "existing_user",
                "email": "existing@example.com",
                "first_name": "Existing",
                "last_name": "User",
                "is_superuser": False,
            },
            "resource_type": "shared.user",
        }

        # Mock the API responses with call counter to simulate resource processing
        # Migration processes orgs, teams, then users - we need to mock all of them
        call_counts = {"shared.organization": 0, "shared.team": 0, "shared.user": 0}

        def mock_list_resources_response(*args, **kwargs):
            filters = kwargs.get('filters', {})
            resource_type = filters.get('content_type__resource_type__name')

            if resource_type == 'shared.user':
                call_counts['shared.user'] += 1
                if call_counts['shared.user'] == 1:
                    return Mock(json=lambda: {"count": 1, "results": [mock_user_resource]})
                else:
                    return Mock(json=lambda: {"count": 0, "results": []})
            else:
                # For organizations and teams, return empty immediately
                return Mock(json=lambda: {"count": 0, "results": []})

        mock_client.list_resources.side_effect = mock_list_resources_response
        mock_client.get_resource.return_value.json.return_value = mock_user_resource
        mock_client.update_resource.return_value = Mock()
        mock_client.list_user_assignments.return_value.json.return_value = {"count": 0, "results": []}

        mock_client_class.return_value = mock_client

        # Run migration
        call_command("migrate_service_data", username=admin_user.username)

        # Verify that the existing user has use_controller_password=False
        existing_user.refresh_from_db()
        assert existing_user.use_controller_password is False


@pytest.mark.django_db(transaction=True)
def test_use_controller_password_save_uses_update_fields():
    """Test that _set_use_controller_password_flag uses update_fields for efficient saves"""

    # Create a user without the flag set
    User.objects.create(username="test_user", use_controller_password=False)

    # Create upstream resource data
    upstream_resource = {
        "resource_data": {
            "username": "test_user",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }
    }

    cmd = MigrateCommand()

    # Patch the save method to verify update_fields is used
    with patch.object(User, 'save') as mock_save:
        cmd._set_use_controller_password_flag(upstream_resource)

        # Verify save was called with update_fields
        mock_save.assert_called_once_with(update_fields=["use_controller_password"])
