from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import ServiceKey


def test_service_key_create_method_not_allowed(admin_api_client):
    """No visible items"""
    url = get_relative_url("service_key-list")
    response = admin_api_client.post(url)
    assert response.status_code == 405


def test_service_key_list_works(admin_api_client, service_cluster_gateway, randname):
    """No visible items"""
    url = get_relative_url("service_key-list")
    random_name = randname("Service Key")
    response = admin_api_client.get(url, {"name": random_name})
    assert response.status_code == 200
    assert response.data["count"] == 0

    ServiceKey.objects.create(
        service_cluster=service_cluster_gateway,
        secret_length=128,
        name=random_name,
    )
    response = admin_api_client.get(url, {"name": random_name})
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["name"] == random_name


# Note, posting and deleting unit tests are in aap_gateway_api/tests/authentication/test_service_token_auth.py
