from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import AdditionalRoute


def test_additional_route_detail(admin_api_client, additional_route_controller):
    url = get_relative_url('route-detail', kwargs={'pk': additional_route_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['id'] == additional_route_controller.pk
    assert response.data['name'] == additional_route_controller.name
    assert response.data['http_port'] == additional_route_controller.http_port.pk
    assert response.data['service_cluster'] == additional_route_controller.service_cluster.pk
    assert response.data['service_path'] == additional_route_controller.service_path
    assert response.data['service_port'] == additional_route_controller.service_port
    assert response.data['description'] == additional_route_controller.description
    assert response.data['gateway_path'] == additional_route_controller.gateway_path
    assert response.data['is_service_https'] == additional_route_controller.is_service_https


def test_additional_route_list(admin_api_client, additional_route_controller, additional_route_eda):
    url = get_relative_url('route-list')
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data["results"]) == 2
    assert response.data["results"][0]['http_port'] == additional_route_controller.http_port.pk
    assert response.data["results"][1]['http_port'] == additional_route_eda.http_port.pk
    assert additional_route_eda.http_port.pk != additional_route_controller.http_port.pk


def test_additional_route_create(admin_api_client, http_port_factory, service_cluster_hub):
    http_port = http_port_factory()
    url = get_relative_url('route-list')
    data = {
        'name': 'test',
        'http_port': http_port.pk,
        'service_cluster': service_cluster_hub.pk,
        'service_path': '/test',
        'service_port': 8080,
        'description': 'test',
        'gateway_path': '/test',
        'is_service_https': False,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert AdditionalRoute.objects.count() == 1
    assert AdditionalRoute.objects.get().name == 'test'
    assert AdditionalRoute.objects.get().http_port == http_port
    assert AdditionalRoute.objects.get().service_cluster == service_cluster_hub
    assert AdditionalRoute.objects.get().service_path == '/test'
    assert AdditionalRoute.objects.get().service_port == 8080
    assert AdditionalRoute.objects.get().description == 'test'
    assert AdditionalRoute.objects.get().gateway_path == '/test'
    assert AdditionalRoute.objects.get().is_service_https is False


def test_additional_route_update(admin_api_client, additional_route_controller):
    url = get_relative_url('route-detail', kwargs={'pk': additional_route_controller.pk})
    data = {
        'name': 'test',
        'http_port': additional_route_controller.http_port.pk,
        'service_cluster': additional_route_controller.service_cluster.pk,
        'service_path': '/test',
        'service_port': 8080,
        'description': 'test',
        'gateway_path': '/test',
        'is_service_https': False,
    }
    response = admin_api_client.put(url, data=data)
    assert response.status_code == 200
    assert AdditionalRoute.objects.count() == 1
    assert AdditionalRoute.objects.get().name == 'test'
    assert AdditionalRoute.objects.get().http_port == additional_route_controller.http_port
    assert AdditionalRoute.objects.get().service_cluster == additional_route_controller.service_cluster
    assert AdditionalRoute.objects.get().service_path == '/test'
    assert AdditionalRoute.objects.get().service_port == 8080
    assert AdditionalRoute.objects.get().description == 'test'
    assert AdditionalRoute.objects.get().gateway_path == '/test'
    assert AdditionalRoute.objects.get().is_service_https is False


def test_additional_route_delete(admin_api_client, additional_route_controller):
    url = get_relative_url('route-detail', kwargs={'pk': additional_route_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert AdditionalRoute.objects.count() == 0


def test_additional_route_delete_unauthenticated(unauthenticated_api_client, additional_route_controller):
    url = get_relative_url('route-detail', kwargs={'pk': additional_route_controller.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401
    assert AdditionalRoute.objects.count() == 1


def test_additional_route_delete_nonexistent(admin_api_client):
    url = get_relative_url('route-detail', kwargs={'pk': 999})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_additional_route_api_port_cannot_start_with_api_prefix(admin_api_client, http_api_port_factory, service_cluster_eda):
    http_port = http_api_port_factory()
    url = get_relative_url('route-list')
    data = {
        'name': 'test',
        'http_port': http_port.pk,
        'service_cluster': service_cluster_eda.pk,
        'service_path': '/test',
        'service_port': 8080,
        'description': 'test',
        'gateway_path': '/api/test',
        'is_service_https': False,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert AdditionalRoute.objects.count() == 0
    assert response.data['gateway_path'][0] == "Custom routes on the API port cannot start with '/api/'"


def test_additional_route_name_must_be_unique(admin_api_client, additional_route_controller):
    url = get_relative_url('route-list')
    data = {
        'name': additional_route_controller.name,
        'http_port': additional_route_controller.http_port.pk,
        'service_cluster': additional_route_controller.service_cluster.pk,
        'service_path': '/test',
        'service_port': 8080,
        'description': 'test',
        'gateway_path': '/test',
        'is_service_https': False,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['name'][0].code == 'unique'
