import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.exceptions import ProxyDenied
from aap_gateway_api.models import ServiceCluster


def test_service_cluster_detail_controller(admin_api_client, service_cluster_controller):
    url = get_relative_url("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "controller"
    assert response.data["service_type"] == "controller"
    assert response.data["service_type"] == service_cluster_controller.service_type


def test_service_cluster_list(admin_api_client, service_cluster_controller, service_cluster_hub, service_cluster_gateway):
    url = get_relative_url("service_cluster-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data["results"]) == 3
    assert response.data["results"][0]["name"] == "controller"
    assert response.data["results"][0]["service_type"] == "controller"
    assert response.data["results"][0]["service_type"] == service_cluster_controller.service_type
    assert response.data["results"][1]["name"] == "hub"
    assert response.data["results"][1]["service_type"] == "hub"
    assert response.data["results"][1]["service_type"] == service_cluster_hub.service_type
    assert response.data["results"][2]["name"] == "gateway"
    assert response.data["results"][2]["service_type"] == "gateway"
    assert response.data["results"][2]["service_type"] == service_cluster_gateway.service_type


def test_service_cluster_create(admin_api_client):
    url = get_relative_url("service_cluster-list")
    response = admin_api_client.post(url, {"name": "My Controller", "service_type": "controller"})
    assert response.status_code == 201
    assert response.data["name"] == "My Controller"
    assert response.data["service_type"] == "controller"
    assert ServiceCluster.objects.filter(pk=response.data["id"]).exists()


def test_service_cluster_update(admin_api_client, service_cluster_controller):
    url = get_relative_url("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.patch(url, {"service_type": "hub"})
    assert response.status_code == 200
    assert response.data["service_type"] == "hub"
    assert ServiceCluster.objects.filter(pk=response.data["id"], service_type="hub").exists()

    response = admin_api_client.patch(url, {"name": "My Automation Hub"})
    assert response.status_code == 200
    assert response.data["name"] == "My Automation Hub"
    assert ServiceCluster.objects.filter(pk=response.data["id"], name="My Automation Hub").exists()


def test_service_cluster_delete(admin_api_client, service_cluster_controller):
    url = get_relative_url("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert not ServiceCluster.objects.filter(pk=service_cluster_controller.pk).exists()


def test_service_cluster_create_with_invalid_type(admin_api_client):
    url = get_relative_url("service_cluster-list")
    response = admin_api_client.post(url, {"service_type": "x"})
    assert response.status_code == 400
    assert response.data["service_type"][0] == '"x" is not a valid choice.'
    assert not ServiceCluster.objects.filter(service_type="x").exists()


def test_service_cluster_update_with_invalid_type(admin_api_client, service_cluster_controller):
    url = get_relative_url("service_cluster-detail", kwargs={"pk": service_cluster_controller.pk})
    response = admin_api_client.patch(url, {"service_type": "x"})
    assert response.status_code == 400
    assert response.data["service_type"][0] == '"x" is not a valid choice.'
    assert not ServiceCluster.objects.filter(pk=service_cluster_controller.pk, service_type="x").exists()


def test_service_cluster_name_must_be_unique(admin_api_client, service_cluster_controller):
    url = get_relative_url('service_cluster-list')
    data = {'name': service_cluster_controller.name, 'service_type': 'hub'}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['name'][0].code == 'unique'


def test_service_cluster_create_with_missing_type(admin_api_client):
    url = get_relative_url("service_cluster-list")
    response = admin_api_client.post(url, {})
    assert response.status_code == 400
    assert response.data["service_type"][0] == "This field is required."
    assert not ServiceCluster.objects.filter().exists()


@pytest.mark.parametrize(
    "endpoint_name,endpoint_fixture",
    [
        ("service_cluster-detail", "service_cluster_gateway"),
        ("service_node-detail", "service_node_gateway"),
        ("service-detail", "service_api_route_gateway"),
        ("http_port-detail", "http_api_port"),
    ],
)
def test_service_model_write_from_proxy(request, admin_api_client, endpoint_name, endpoint_fixture):
    endpoint_object = request.getfixturevalue(endpoint_fixture)
    url = get_relative_url(endpoint_name, kwargs={"pk": endpoint_object.pk})
    extras = {"HTTP_X_TRUSTED_PROXY": "True"}

    response = admin_api_client.put(url, **extras)
    assert response.status_code == 403
    assert str(ProxyDenied.default_detail) in str(response.content)

    response = admin_api_client.delete(url, **extras)
    assert response.status_code == 403
    assert str(ProxyDenied.default_detail) in str(response.content)
