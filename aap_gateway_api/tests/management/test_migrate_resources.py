from unittest.mock import patch

import pytest
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.core.management import call_command
from rest_framework.test import APIClient

from aap_gateway_api.models import MigratedUserMetadata, Organization, Route, Team, User
from aap_gateway_api.tests.conftest import PatchedResourceClient
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
def test_migrate_no_merge(migration_service, admin_user, admin_api_client, conflicting_org, conflicting_team, patched_resource_client):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", api_slug=migration_service.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=False)

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Check that the org with the conflicting name was prefixed with the api slug
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert Organization.objects.filter(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name).exists()

    # Since orgs are not merged, team names should be the same.
    original_org_teams = list(conflicting_org.teams.all().values_list("name", flat=True))
    assert original_org_teams == [conflicting_team.name]

    new_org = Organization.objects.get(name=migration_service.api_slug + SEP_CHAR + conflicting_org.name)

    new_org_teams = list(new_org.teams.all().values_list("name", flat=True))
    assert new_org_teams == [conflicting_team.name]

    # Check that the org was renamed on the services.
    updated_org = service_client.get_resource(str(new_org.resource.ansible_id)).json()
    assert updated_org["name"] == migration_service.api_slug + SEP_CHAR + conflicting_org.name


@pytest.mark.django_db(transaction=True)
def test_migrate_merge_orgs(
    migration_service,
    admin_user,
    service_api_route_controller,
    admin_api_client,
    conflicting_org,
    conflicting_team,
    patched_resource_client,
):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=False,
        merge_organizations=True,
    )

    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

    # Check that only one organization exists
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=service_api_route_controller.api_slug + SEP_CHAR + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert Team.objects.filter(organization=conflicting_org, name=service_api_route_controller.api_slug + SEP_CHAR + conflicting_team.name).exists()


@pytest.mark.django_db(transaction=True)
def test_migrate_merge_orgs_and_teams(
    migration_service,
    admin_user,
    service_api_route_controller,
    admin_api_client,
    conflicting_org,
    conflicting_team,
    patched_resource_client,
):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data", api_slug=service_api_route_controller.api_slug, username=admin_user.username, merge_teams=True, merge_organizations=True
    )

    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

    # Check that only one organization exists
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=service_api_route_controller.api_slug + SEP_CHAR + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(organization=conflicting_org, name=service_api_route_controller.api_slug + SEP_CHAR + conflicting_team.name).exists()


@pytest.mark.django_db(transaction=True)
def test_migrate_conflicting_user(
    migration_service,
    admin_user,
    service_api_route_controller,
    service_api_route_hub,
    admin_api_client,
    patched_resource_client,
):
    # Check that users do not exist yet
    assert not User.objects.filter(username="natasha").exists()
    assert not User.objects.filter(username="hawkeye").exists()

    # Create a conflict
    u = User.objects.create(username="hawkeye")
    MigratedUserMetadata.objects.create(user=u, service=service_api_route_hub.service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
    )

    pre_sync_resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "content_type__resource_type__name": "shared.user",
            "not__name": admin_user.username,  # admin user will be merged, and thus get the gateway service_id
        }
    ).json()

    assert len(pre_sync_resources['results']) > 0

    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

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
    service_api_route_controller,
    service_api_route_hub,
    admin_api_client,
    patched_resource_client,
):
    # Create a conflict
    u = User.objects.create(username="hawkeye", email="hawkeye@secretbase.invalid")
    MigratedUserMetadata.objects.create(user=u, service=service_api_route_hub.service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)
    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
    )
    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

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
    service_api_route_controller,
    patched_resource_client,
):
    """Verify that a service user resource with the same ansible id but a differing
    service id from gateway's has its service id corrected to gateway's via migration.
    """
    # First, perform a migration to bring our test user ("fury") to gateway.
    # The migration preserves
    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
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
    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
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

    cmd = MigrateCommand()
    cmd.service_slug = 'controller'

    call_command(cmd, api_slug=migration_service_invalid_users.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=False)

    users = User.objects.filter(username="bademailuser1")
    assert users is not None and users.exists()
    for u in users:
        assert u.first_name == "Badema"
        assert u.last_name == "Iluser"
        assert u.email == ""


@pytest.mark.django_db(transaction=True)
def test_updating_resource_data_for_invalid_resource(migration_service_invalid_users, admin_user):
    from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand

    with patch.object(MigrateCommand, "update_resource_data") as mocked_update_resource_data_method:
        mocked_update_resource_data_method.return_value = None  # None indicates that its data could not be updated

        cmd = MigrateCommand()
        cmd.service_slug = 'controller'

        with pytest.raises(RuntimeError):
            call_command(cmd, api_slug=migration_service_invalid_users.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=False)

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
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username') == 'controller_foouser'

    # If user bob exists that should not affect the result
    User.objects.create(username='bob')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username') == 'controller_foouser'


@pytest.mark.django_db
def test_use_given_name_iteration(cmd):
    User.objects.create(username='controller_foouser')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username') == 'controller_foouser1'

    User.objects.create(username='controller_foouser1')
    User.objects.create(username='controller_foouser2')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username') == 'controller_foouser3'


@pytest.mark.django_db(transaction=True)
def test_migrated_admin_password(
    migration_service,
    admin_user,
    service_api_route_controller,
    admin_api_client,
    patched_resource_client,
):
    admin_user.set_password(None)
    admin_user.save()
    admin_user.authenticator_users.all().delete()

    assert admin_user.username == "admin"

    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
    )

    assert admin_user.authenticator_users.filter(
        provider__type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
    ).exists()

    url = get_relative_url("login")
    next_url = get_relative_url("me-list")

    with patch("aap_gateway_api.authentication.authenticator_plugins.controller_admin.GWResourceAPIClient", PatchedResourceClient):
        client = APIClient()
        data = {"username": "admin", "password": "invalid_password", "next": next_url}
        response = client.post(url, data, follow=True)
        assert response.status_code == 401

        client = APIClient()
        data = {"username": "admin", "password": "controller_admin_pass", "next": next_url}
        response = client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.data["results"][0]["username"] == "admin"

        assert not admin_user.authenticator_users.filter(
            provider__type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
        ).exists()

        assert not Authenticator.objects.filter(
            type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
        ).exists()

        # make sure we can login with the new password
        client = APIClient()
        data = {"username": "admin", "password": "controller_admin_pass", "next": next_url}
        response = client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.data["results"][0]["username"] == "admin"


@pytest.mark.django_db(transaction=True)
def test_admin_user_already_set_migrated_admin_password(
    migration_service,
    admin_user,
    service_api_route_controller,
    admin_api_client,
    patched_resource_client,
):
    admin_user.set_password("admin")
    admin_user.save()

    assert admin_user.username == "admin"

    call_command(
        "migrate_service_data",
        api_slug=service_api_route_controller.api_slug,
        username=admin_user.username,
        merge_teams=True,
        merge_organizations=True,
    )

    assert not admin_user.authenticator_users.filter(
        provider__type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
    ).exists()

    assert not Authenticator.objects.filter(
        type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
    ).exists()

    url = get_relative_url("login")
    next_url = get_relative_url("me-list")

    with patch("aap_gateway_api.authentication.authenticator_plugins.controller_admin.GWResourceAPIClient", PatchedResourceClient):
        data = {"username": "admin", "password": "admin", "next": next_url}

        client = APIClient()
        response = client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.data["results"][0]["username"] == "admin"

        data = {"username": "admin", "password": "controller_admin_pass", "next": next_url}

        client = APIClient()
        response = client.post(url, data, follow=True)
        assert response.status_code == 401
