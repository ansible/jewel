from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.core.management import call_command
from django.db import IntegrityError

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
def test_migrate_with_ignored_flags(migration_service, admin_user, admin_api_client, conflicting_org, conflicting_team, patched_resource_client, capsys):
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
    assert User.objects.filter(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').exists()

    renamed_user = User.objects.get(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye')

    assert renamed_user.original_accounts.count() == 1
    original_data = renamed_user.original_accounts.get(service=migration_service.service_cluster)
    assert original_data.original_username == "hawkeye"

    assert renamed_user.authenticator_users.filter(uid="mr_hawk").exists()

    updated_resource = service_client.get_resource(str(renamed_user.resource.ansible_id)).json()
    assert updated_resource

    # When merge_users=False, users should get partially migrated
    assert updated_resource["is_partially_migrated"] is True

    # We set is_partially_migrated=True for this user in the fixture, so it should not get migrated
    assert not User.objects.filter(username="already_migrated").exists()

    resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "content_type__resource_type__name": "shared.user",
            "not__name": admin_user.username,  # admin user will be merged, and thus get the gateway service_id
        }
    ).json()

    # Check that the user's service ID's were not updated
    assert resources["count"] == pre_sync_resources["count"]

    assert renamed_user.resource.service_id == migration_service.service_cluster.service_id


@pytest.mark.django_db(transaction=True)
def test_merge_users(
    migration_service,
    admin_user,
    admin_api_client,
    patched_resource_client,
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
    assert User.objects.get(username="hawkeye").original_accounts.count() == 1

    conflict_user = User.objects.get(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye')
    assert conflict_user.original_accounts.count() == 1
    updated_resource = service_client.get_resource(str(conflict_user.resource.ansible_id)).json()
    assert updated_resource

    # Users always do oppionated merge_users=True behavior
    # for any renamed user, we will set the partially migrated flag
    assert updated_resource["is_partially_migrated"] is True

    updated_user = updated_resource['resource_data']
    assert updated_user.get('username') == f'{service_client.service.api_slug}{SEP_CHAR}hawkeye', updated_user

    assert User.objects.get(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').authenticator_users.filter(uid="mr_hawk").exists()

    # We set is_partially_migrated=True for this user in the fixture, so it should not get migrated
    assert not User.objects.filter(username="already_migrated").exists()


@pytest.mark.django_db(transaction=True)
def test_correcting_user_service_id(
    migration_service,
    admin_user,
    patched_resource_client,
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
def test_migrating_user_with_invalid_email(migration_service_invalid_users, admin_user):
    from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand

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
def test_updating_resource_data_for_invalid_resource(migration_service_invalid_users, admin_user):
    from django.core.management.base import CommandError

    from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand

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
    # By using patched_resource_client fixture before importing this, the mock should remain active
    from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand

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
    with patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class:
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
        assert len(processing_lines) == 3
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
        patch('aap_gateway_api.management.commands.migrate_service_data.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
    ):

        from requests.exceptions import HTTPError

        # Mock JWT creation to avoid public key parsing issues
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'

        def mock_client_factory(service_api, *args, **kwargs):
            import uuid

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
