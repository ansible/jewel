import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from django.core.management import call_command

from aap_gateway_api.models import Organization, Team
from aap_gateway_api.tests.service_test_app.launch import launch_service


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


@pytest.mark.django_db(transaction=True)
def test_migrate_no_merge(migration_service, admin_user, admin_api_client, conflicting_org, conflicting_team, patched_resource_client):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", api_slug=migration_service.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=False)

    _assert_all_resources_synced(admin_api_client, migration_service, service_client)

    # Check that the org with the conflicting name was prefixed with the api slug
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert Organization.objects.filter(name=migration_service.api_slug + ":" + conflicting_org.name).exists()

    # Since orgs are not merged, team names should be the same.
    original_org_teams = list(conflicting_org.teams.all().values_list("name", flat=True))
    assert original_org_teams == [conflicting_team.name]

    new_org = Organization.objects.get(name=migration_service.api_slug + ":" + conflicting_org.name)

    new_org_teams = list(new_org.teams.all().values_list("name", flat=True))
    assert new_org_teams == [conflicting_team.name]

    # Check that the org was renamed on the services.
    updated_org = service_client.get_resource(str(new_org.resource.ansible_id)).json()
    assert updated_org["name"] == migration_service.api_slug + ":" + conflicting_org.name


@pytest.mark.django_db(transaction=True)
def test_migrate_merge_orgs(
    migration_service, admin_user, service_api_route_controller, admin_api_client, conflicting_org, conflicting_team, patched_resource_client
):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data", api_slug=service_api_route_controller.api_slug, username=admin_user.username, merge_teams=False, merge_organizations=True
    )

    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

    # Check that only one organization exists
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=service_api_route_controller.api_slug + ":" + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert Team.objects.filter(organization=conflicting_org, name=service_api_route_controller.api_slug + ":" + conflicting_team.name).exists()


@pytest.mark.django_db(transaction=True)
def test_migrate_merge_orgs_and_teams(
    migration_service, admin_user, service_api_route_controller, admin_api_client, conflicting_org, conflicting_team, patched_resource_client
):
    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command(
        "migrate_service_data", api_slug=service_api_route_controller.api_slug, username=admin_user.username, merge_teams=True, merge_organizations=True
    )

    _assert_all_resources_synced(admin_api_client, service_api_route_controller, service_client)

    # Check that only one organization exists
    assert Organization.objects.filter(name=conflicting_org.name).exists()
    assert not Organization.objects.filter(name=service_api_route_controller.api_slug + ":" + conflicting_org.name).exists()

    assert Team.objects.filter(organization=conflicting_org, name=conflicting_team.name).exists()
    assert not Team.objects.filter(organization=conflicting_org, name=service_api_route_controller.api_slug + ":" + conflicting_team.name).exists()
