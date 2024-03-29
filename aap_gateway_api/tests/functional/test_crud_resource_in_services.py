import pytest
from django.urls import reverse

from aap_gateway_api.models import Organization, Team, User


def _assert_resource_identical(resource, resource_client):
    serializer = resource.content_type.resource_type.serializer_class

    gateway_data = serializer(resource.content_object).data
    service_data = resource_client.MOCKED_API.detail(str(resource.ansible_id))

    for k in gateway_data.keys():
        assert gateway_data[k] == service_data["resource_data"][k]


def _assert_resource_deleted(resource, resource_client):
    assert str(resource.ansible_id) not in resource_client.MOCKED_API.resources


@pytest.mark.django_db(transaction=True)
def test_organizations_are_updated(mocked_resources_client, admin_user, service_api_route_controller, admin_api_client):
    org_name = "My test org"

    url = reverse("organization-list")
    response = admin_api_client.post(url, data={"name": org_name})
    assert response.status_code == 201

    resource = Organization.objects.get(name=org_name).resource

    _assert_resource_identical(resource, mocked_resources_client)

    url = reverse("organization-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.put(url, data={"name": "New Org Name"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, mocked_resources_client)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, mocked_resources_client)


@pytest.mark.django_db(transaction=True)
def test_users_are_updated(mocked_resources_client, admin_user, service_api_route_controller, admin_api_client):
    username = "my_username"

    url = reverse("user-list")
    response = admin_api_client.post(url, data={"username": username, "password": "supersecret"})
    assert response.status_code == 201

    resource = User.objects.get(username=username).resource

    _assert_resource_identical(resource, mocked_resources_client)

    url = reverse("user-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"email": "hello@aol.com", "first_name": "bob", "last_name": "bobberton"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, mocked_resources_client)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, mocked_resources_client)


@pytest.mark.django_db(transaction=True)
def test_teams_are_updated(mocked_resources_client, admin_user, service_api_route_controller, admin_api_client, organization):
    team_name = "my cool team"

    url = reverse("team-list")
    response = admin_api_client.post(url, data={"name": team_name, "organization": organization.pk})
    assert response.status_code == 201

    resource = Team.objects.get(name=team_name).resource

    _assert_resource_identical(resource, mocked_resources_client)

    url = reverse("team-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"name": "hello world!"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, mocked_resources_client)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, mocked_resources_client)
