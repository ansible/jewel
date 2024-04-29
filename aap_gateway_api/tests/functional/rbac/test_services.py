import pytest
from django.urls import reverse


@pytest.fixture
def service_objects(service_cluster_eda, service_node_eda, service_api_route_eda, additional_route_eda):
    http_port_eda = additional_route_eda.http_port
    return dict(
        service_cluster=service_cluster_eda,
        service_node=service_node_eda,
        service=service_api_route_eda,
        route=additional_route_eda,
        http_port=http_port_eda,
    )


def test_services_list_permissions(user_api_client, service_objects):
    """No visible items"""
    for basename, svc_object in service_objects.items():
        url = reverse(f"{basename}-list")

        response = user_api_client.get(url)
        assert response.status_code == 403


def test_services_detail_permissions(user_api_client, service_objects):
    """No visible items"""
    for basename, svc_object in service_objects.items():
        # Server should consistently give the bad status code for existing and missing objects
        for obj_pk in (svc_object.pk, 12345):
            url = reverse(f"{basename}-detail", kwargs={"pk": obj_pk})
            response = user_api_client.get(url)
            assert response.status_code == 403, f"Object {basename} shouldn't be found"


def test_services_create_permissions(user_api_client, service_objects, randname):
    """Forbidden"""
    for basename, svc_object in service_objects.items():
        random_name = randname(f"Test {basename.upper()}")
        url = reverse(f"{basename}-list")

        response = user_api_client.post(url, data={"name": random_name})
        assert response.status_code == 403, f"Creating {basename} should be forbidden"


@pytest.mark.parametrize("method", ["put", "patch"])
def test_services_update_permissions(user_api_client, service_objects, method, randname):
    """No visible items"""
    for basename, svc_object in service_objects.items():
        for obj_pk in (svc_object.pk, 12345):
            random_name = randname(f"Test-{basename.upper()}-Changed")
            url = reverse(f"{basename}-detail", kwargs={"pk": obj_pk})

            user_api_call = getattr(user_api_client, method)
            response = user_api_call(url, data={"name": random_name})
            assert response.status_code == 403, f"Object {basename} should be invisible for updating"


def test_services_delete_permissions(user_api_client, service_objects):
    """No visible items"""
    for basename, svc_object in service_objects.items():
        for obj_pk in (svc_object.pk, 12345):
            url = reverse(f"{basename}-detail", kwargs={"pk": obj_pk})
            response = user_api_client.delete(url)
            assert response.status_code == 403, f"Object {basename} shouldn't be found"
