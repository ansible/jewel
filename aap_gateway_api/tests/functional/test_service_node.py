from django.urls import reverse

from aap_gateway_api.models import ServiceNode


def test_service_node_detail(admin_api_client, service_node_controller):
    url = reverse("service_node-detail", kwargs={"pk": service_node_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == service_node_controller.name
    assert response.data["address"] == service_node_controller.address
    assert response.data["service"] == service_node_controller.service.pk


def test_service_node_list(admin_api_client, service_node_controller, service_node_hub):
    url = reverse("service_node-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert service_node_controller.name in [node["name"] for node in response.data["results"]]
    assert service_node_hub.name in [node["name"] for node in response.data["results"]]
    assert service_node_controller.address in [node["address"] for node in response.data["results"]]
    assert service_node_hub.address in [node["address"] for node in response.data["results"]]


def test_service_node_create(admin_api_client, service_node_controller):
    url = reverse("service_node-list")
    data = {"name": "Node 10.10.10.10 for Controller", "address": "10.10.10.10", "service": service_node_controller.service.pk}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert ServiceNode.objects.filter(address="10.10.10.10").exists()
    assert ServiceNode.objects.filter(name="Node 10.10.10.10 for Controller").exists()


def test_service_node_update(admin_api_client, service_node_controller):
    url = reverse("service_node-detail", kwargs={"pk": service_node_controller.pk})
    data = {"address": "10.10.10.99"}
    response = admin_api_client.patch(url, data=data)
    assert response.status_code == 200
    assert ServiceNode.objects.filter(address="10.10.10.99").exists()


def test_service_node_delete(admin_api_client, service_node_controller):
    url = reverse("service_node-detail", kwargs={"pk": service_node_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert not ServiceNode.objects.filter(pk=service_node_controller.pk).exists()
