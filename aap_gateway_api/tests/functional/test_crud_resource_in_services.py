import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import Organization, ServiceAPIRoute, Team, User


def _assert_resource_identical(resource, patched_client, admin_user):
    serializer = resource.content_type.resource_type.serializer_class

    services = ServiceAPIRoute.objects.all()
    assert services.count() == 3
    for service in services:
        resource_client = patched_client(service, user=admin_user, raise_if_bad_request=True)
        gateway_data = serializer(resource.content_object).data
        service_data = resource_client.get_resource(str(resource.ansible_id)).json()

        for k in gateway_data.keys():
            assert gateway_data[k] == service_data["resource_data"][k]


def _assert_resource_deleted(resource, patched_client, admin_user):
    services = ServiceAPIRoute.objects.all()
    assert services.count() == 3
    for service in services:
        resource_client = patched_client(service, user=admin_user, raise_if_bad_request=False)
        assert resource_client.get_resource(str(resource.ansible_id)).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_organizations_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
):
    org_name = "My test org"
    url = get_relative_url("organization-list")
    response = admin_api_client.post(url, data={"name": org_name})
    assert response.status_code == 201

    resource = Organization.objects.get(name=org_name).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("organization-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.put(url, data={"name": "New Org Name"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)


@pytest.mark.django_db(transaction=True)
def test_users_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
):
    username = "my_username"

    url = get_relative_url("user-list")
    response = admin_api_client.post(url, data={"username": username, "password": "supersecret"})
    assert response.status_code == 201

    resource = User.objects.get(username=username).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("user-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"email": "hello@aol.com", "first_name": "bob", "last_name": "bobberton"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)


@pytest.mark.django_db(transaction=True)
def test_teams_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
):
    url = get_relative_url("organization-list")
    response = admin_api_client.post(url, data={"name": "my_org_name"})
    assert response.status_code == 201
    org = response.json()

    team_name = "my cool team"

    url = get_relative_url("team-list")
    response = admin_api_client.post(url, data={"name": team_name, "organization": org["id"]})
    assert response.status_code == 201

    resource = Team.objects.get(name=team_name).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("team-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"name": "hello world!"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)
