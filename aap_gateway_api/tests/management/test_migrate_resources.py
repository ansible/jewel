import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from django.core.management import call_command

from aap_gateway_api.models import MigratedUserMetadata, Organization, Team, User
from aap_gateway_api.tests.service_test_app.launch import launch_service

SEP_CHAR = "_"


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
def migration_service(patched_resource_client, service_api_route_controller):
    proc = launch_service("awx", service_api_route_controller.service_port, setup_fixture="migration_tests")
    yield service_api_route_controller
    proc.kill()
    stdout, stderr = proc.communicate()
    if stdout:
        print('')
        print('AWX standard out:')
        print(str(stdout, encoding='utf-8'))
    if stderr:
        print('')
        print('AWX standard err:')
        print(str(stderr, encoding='utf-8'))


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
