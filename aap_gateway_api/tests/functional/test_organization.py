import pytest
from django.urls import reverse

from aap_gateway_api.models import Organization


def test_organizations_list(admin_api_client, organization):
    url = reverse("organization-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == organization.name


@pytest.mark.parametrize(
    "key, route",
    [
        ("users", "organization-users-list"),
        ("admins", "organization-admins-list"),
        ("teams", "organization-teams-list"),
    ],
)
def test_organizations_related_fields(admin_api_client, organization, key, route):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    organization = response.data
    assert key in organization["related"]
    assert organization["related"][key] == reverse(route, kwargs={"pk": organization["id"]})


def test_organizations_list_unauthenticated(unauthenticated_api_client):
    url = reverse("organization-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


def test_organizations_create(admin_api_client, randname):
    url = reverse("organization-list")
    random_name = randname("Test Organization")
    response = admin_api_client.post(url, data={"name": random_name})
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == random_name


@pytest.mark.parametrize(
    "description",
    [
        "A test organization, which is thusly described.",
        "",
        None,
    ],
)
def test_organizations_create_description_is_optional(admin_api_client, randname, description):
    url = reverse("organization-list")
    random_name = randname("Test Organization")
    data = {"name": random_name}
    if description is not None:
        data["description"] = description
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == random_name
    if description is not None:
        assert results[0]["description"] == description
    else:
        assert results[0]["description"] == ""


def test_organizations_create_unauthenticated(unauthenticated_api_client, randname):
    url = reverse("organization-list")
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.post(url, data={"name": random_name})
    assert response.status_code == 401
    assert Organization.objects.filter(name=random_name).count() == 0


def test_organizations_update(admin_api_client, organization, randname):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    random_name = randname("Test Organization")
    response = admin_api_client.put(url, data={"name": random_name})
    assert response.status_code == 200
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == random_name


def test_organizations_update_unauthenticated(unauthenticated_api_client, organization, randname):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.put(url, data={"name": random_name})
    assert response.status_code == 401


def test_organizations_delete(admin_api_client, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204

    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_organizations_delete_unauthenticated(unauthenticated_api_client, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_organizations_delete_nonexistent(admin_api_client):
    url = reverse("organization-detail", kwargs={"pk": 999})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_organizations_users_associate(admin_api_client, organization, user):
    """
    Test that we can associate users with an organization.
    """
    url = reverse("organization-users-associate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.users.count() == 1
    assert user in organization.users.all()


def test_organizations_summary_fields_counts(admin_api_client, organization, organization_1, user, team, team_1):
    url = reverse("organization-detail", kwargs={"pk": organization_1.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["related_field_counts"]["users"] == 0
    assert response.data["summary_fields"]["related_field_counts"]["teams"] == 0

    organization_1.users.add(user)
    organization_1.teams.add(team, team_1)
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["related_field_counts"]["users"] == 1
    assert response.data["summary_fields"]["related_field_counts"]["teams"] == 2


def test_organizations_admins_association(admin_api_client, organization, user):
    """
    Test that we can (dis)associate admins with an organization (from the org side).
    """
    assert organization.admins.count() == 0

    url = reverse("organization-admins-associate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.admins.count() == 1
    assert organization.admins.first() == user

    url = reverse("organization-admins-disassociate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.admins.count() == 0


def test_organizations_resource_summary_fields(admin_api_client, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["resource"]["ansible_id"] == organization.resource.ansible_id
    assert response.data["summary_fields"]["resource"]["resource_type"] == organization.resource.resource_type
