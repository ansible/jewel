import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.views.api.v1.service_key import ServiceKeyBrowsableAPIRenderer, ServiceKeyViewSet, deprecation_message


def test_service_key_create_method_not_allowed(admin_api_client):
    """POST returns the service-key deprecation response."""
    url = get_relative_url("service_key-list")
    response = admin_api_client.post(url)
    assert response.status_code == 405
    assert response.data["detail"] == (
        "For security reasons, creating service keys through this API is no longer supported. "
        "To create a key for a registered service, run "
        "`aap-gateway-manage generate_service_secret <service_cluster_name>` in the Gateway environment."
    )


def test_service_key_post_form_is_hidden_from_browsable_api():
    renderer = ServiceKeyBrowsableAPIRenderer()

    assert renderer.show_form_for_method(ServiceKeyViewSet(), "POST", None, None) is False


def test_service_key_view_exposes_deprecation_messages():
    assert ServiceKeyViewSet.deprecated is True
    assert ServiceKeyViewSet.deprecated_message == deprecation_message
    assert ServiceKeyViewSet.deprecation_warning_header_override == "HTTP POST method is no longer supported for this endpoint."


@pytest.mark.parametrize("method", ["patch", "put"])
def test_service_key_updates_ignore_deprecated_create_fields(
    admin_api_client,
    method,
    service_key_factory,
    service_cluster_eda,
    service_cluster_gateway,
):
    key = service_key_factory(service_cluster_eda)
    original_secret = key.secret
    url = get_relative_url("service_key-detail", kwargs={"pk": key.pk})
    payload = {
        "name": key.name,
        "is_active": False,
        "service_cluster": service_cluster_gateway.pk,
        "secret": "replacement-secret",
        "secret_length": 128,
        "mark_previous_inactive": True,
        "algorithm": "HS512",
    }

    response = getattr(admin_api_client, method)(url, data=payload, format="json")

    assert response.status_code == 200
    key.refresh_from_db()
    assert key.is_active is False
    assert key.service_cluster == service_cluster_eda
    assert key.secret == original_secret
    assert key.algorithm == "HS256"


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
