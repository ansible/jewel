import pytest

from django.urls import reverse

from aap_gateway_api.models import Environment


def test_environments_list(admin_api_client, environment):
    url = reverse("environment-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == environment.name


def test_environments_list_unauthenticated(unauthenticated_api_client):
    url = reverse("environment-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 403


def test_environments_create(admin_api_client, randname):
    url = reverse("environment-list")
    random_name = randname("Test Environment")
    response = admin_api_client.post(url, data={"name": random_name})
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == random_name


def test_environments_create_unauthenticated(unauthenticated_api_client, randname):
    url = reverse("environment-list")
    random_name = randname("Test Environment")
    response = unauthenticated_api_client.post(url, data={"name": random_name})
    assert response.status_code == 403
    assert Environment.objects.filter(name=random_name).count() == 0


def test_environments_update(admin_api_client, environment, randname):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    random_name = randname("Test Environment")
    response = admin_api_client.put(url, data={"name": random_name})
    assert response.status_code == 200
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == random_name


def test_environments_update_unauthenticated(
    unauthenticated_api_client, environment, randname
):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    random_name = randname("Test Environment")
    response = unauthenticated_api_client.put(url, data={"name": random_name})
    assert response.status_code == 403
    assert Environment.objects.filter(name=random_name).count() == 0


def test_environments_delete(admin_api_client, environment):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert Environment.objects.filter(pk=environment.pk).count() == 0


def test_environments_delete_unauthenticated(unauthenticated_api_client, environment):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 403
    assert Environment.objects.filter(pk=environment.pk).count() == 1


def test_environments_delete_nonexistent(admin_api_client):
    url = reverse("environment-detail", kwargs={"pk": 999})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_environments_retrieve(admin_api_client, environment):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == environment.name


def test_environments_retrieve_unauthenticated(unauthenticated_api_client, environment):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 403


def test_environments_retrieve_nonexistent(admin_api_client):
    url = reverse("environment-detail", kwargs={"pk": 999})
    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_environments_partial_update(admin_api_client, environment, randname):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    random_name = randname("Test Environment")
    response = admin_api_client.patch(url, data={"name": random_name})
    assert response.status_code == 200
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == random_name


def test_environments_partial_update_unauthenticated(
    unauthenticated_api_client, environment, randname
):
    url = reverse("environment-detail", kwargs={"pk": environment.pk})
    random_name = randname("Test Environment")
    response = unauthenticated_api_client.patch(url, data={"name": random_name})
    assert response.status_code == 403
    assert Environment.objects.filter(name=random_name).count() == 0


def test_environments_partial_update_nonexistent(admin_api_client, randname):
    url = reverse("environment-detail", kwargs={"pk": 999})
    random_name = randname("Test Environment")
    response = admin_api_client.patch(url, data={"name": random_name})
    assert response.status_code == 404
    assert Environment.objects.filter(name=random_name).count() == 0


def test_environments_filter(admin_api_client, environment):
    url = reverse("environment-list")
    response = admin_api_client.get(url, data={"name": environment.name})
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == environment.name


def test_environments_filter_unauthenticated(unauthenticated_api_client, environment):
    url = reverse("environment-list")
    response = unauthenticated_api_client.get(url, data={"name": environment.name})
    assert response.status_code == 403


def test_environments_filter_nonexistent(admin_api_client):
    url = reverse("environment-list")
    response = admin_api_client.get(url, data={"name": "nonexistent"})
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 0
