from django.urls import reverse

from aap_gateway_api.models import ServiceCluster


def test_service_cluster_detail_controller(admin_api_client, service_cluster_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["service_type"] == "c"
    assert response.data["service_type"] == service_cluster_controller.service_type


def test_service_cluster_list(admin_api_client, service_cluster_controller, service_cluster_hub, service_cluster_gateway):
    url = reverse("service_cluster-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data["results"]) == 3
    assert response.data["results"][0]["service_type"] == "c"
    assert response.data["results"][0]["service_type"] == service_cluster_controller.service_type
    assert response.data["results"][1]["service_type"] == "h"
    assert response.data["results"][1]["service_type"] == service_cluster_hub.service_type
    assert response.data["results"][2]["service_type"] == "g"
    assert response.data["results"][2]["service_type"] == service_cluster_gateway.service_type


def test_service_cluster_create(admin_api_client):
    url = reverse("service_cluster-list")
    response = admin_api_client.post(url, {"service_type": "c"})
    assert response.status_code == 201
    assert response.data["service_type"] == "c"
    assert ServiceCluster.objects.filter(pk=response.data["id"]).exists()


def test_service_cluster_update(admin_api_client, service_cluster_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.patch(url, {"service_type": "h"})
    assert response.status_code == 200
    assert response.data["service_type"] == "h"
    assert ServiceCluster.objects.filter(pk=response.data["id"], service_type="h").exists()


def test_service_cluster_delete(admin_api_client, service_cluster_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert not ServiceCluster.objects.filter(pk=service_cluster_controller.pk).exists()


def test_service_cluster_create_with_invalid_type(admin_api_client):
    url = reverse("service_cluster-list")
    response = admin_api_client.post(url, {"service_type": "x"})
    assert response.status_code == 400
    assert response.data["service_type"][0] == '"x" is not a valid choice.'
    assert not ServiceCluster.objects.filter(service_type="x").exists()


def test_service_cluster_update_with_invalid_type(admin_api_client, service_cluster_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.patch(url, {"service_type": "x"})
    assert response.status_code == 400
    assert response.data["service_type"][0] == '"x" is not a valid choice.'
    assert not ServiceCluster.objects.filter(pk=service_cluster_controller.pk, service_type="x").exists()


def test_service_cluster_create_with_missing_type(admin_api_client):
    url = reverse("service_cluster-list")
    response = admin_api_client.post(url, {})
    assert response.status_code == 400
    assert response.data["service_type"][0] == "This field is required."
    assert not ServiceCluster.objects.filter().exists()
