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


def test_organizations_list_unauthenticated(unauthenticated_api_client):
    url = reverse("organization-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 403


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


def test_organizations_create_unauthenticated(unauthenticated_api_client, randname):
    url = reverse("organization-list")
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.post(url, data={"name": random_name})
    assert response.status_code == 403
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


def test_organizations_update_unauthenticated(
    unauthenticated_api_client, organization, randname
):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.put(url, data={"name": random_name})
    assert response.status_code == 403


def test_organizations_delete(admin_api_client, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204

    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_organizations_delete_unauthenticated(unauthenticated_api_client, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 403


def test_organizations_delete_nonexistent(admin_api_client):
    url = reverse("organization-detail", kwargs={"pk": 999})
    response = admin_api_client.delete(url)
    assert response.status_code == 404
