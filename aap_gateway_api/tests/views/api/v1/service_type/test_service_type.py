from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import ServiceCluster, ServiceType


def test_service_type_detail_controller(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "controller"
    assert response.data["id"] == service_type_controller.pk
    assert response.data["ping_url"] == "/api/v2/ping/"


def test_service_type_list(admin_api_client, service_type_controller, service_type_hub, service_type_gateway, service_type_eda):
    url = get_relative_url("service_type-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data["results"]) == 4
    assert response.data["results"][0]["name"] == "gateway"
    assert response.data["results"][0]["id"] == service_type_gateway.pk
    assert response.data["results"][1]["name"] == "controller"
    assert response.data["results"][1]["id"] == service_type_controller.pk
    assert response.data["results"][2]["name"] == "hub"
    assert response.data["results"][2]["id"] == service_type_hub.pk
    assert response.data["results"][3]["name"] == "eda"
    assert response.data["results"][3]["id"] == service_type_eda.pk


def test_service_type_create(admin_api_client):
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {"name": "My New Service Type", "ping_url": "/ping/"})
    assert response.status_code == 201
    assert response.data["name"] == "My New Service Type"
    assert response.data["id"] > 3
    assert ServiceType.objects.filter(pk=response.data["id"]).exists()
    assert ServiceType.objects.filter(pk=response.data["id"]).first().ping_url == "/ping/"


def test_service_type_update(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.patch(url, {"name": "My Hub"})
    assert response.status_code == 200
    assert response.data["id"] == service_type_controller.pk
    assert ServiceType.objects.filter(pk=response.data["id"], name="My Hub").exists()


def test_service_type_delete(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert not ServiceType.objects.filter(pk=service_type_controller.pk).exists()
    assert ServiceCluster.get_cluster_by_type(service_type=service_type_controller.pk) is None


def test_service_type_name_must_be_unique(admin_api_client, service_type_controller):
    url = get_relative_url('service_type-list')
    data = {'name': service_type_controller.name, 'ping_url': '/ping/'}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['name'][0].code == 'unique'


def test_service_type_create_with_missing_name(admin_api_client):
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {'ping_url': '/ping/'})
    assert response.status_code == 400
    assert response.data["name"][0] == "This field is required."
    assert not ServiceType.objects.filter(name='').exists()
