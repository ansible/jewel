import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.urls import reverse

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.views.api.v1.service_key import POST_DEPRECATION_MESSAGE, UPDATE_DEPRECATION_MESSAGE, ServiceKeyBrowsableAPIRenderer, ServiceKeyViewSet


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
    assert {method.strip() for method in response["Allow"].split(",")} == {"GET", "HEAD", "OPTIONS"}


def test_service_key_post_form_is_hidden_from_browsable_api():
    renderer = ServiceKeyBrowsableAPIRenderer()

    assert renderer.show_form_for_method(ServiceKeyViewSet(), "POST", None, None) is False


def test_service_key_options_does_not_advertise_post(admin_api_client):
    response = admin_api_client.options(get_relative_url("service_key-list"))

    assert response.status_code == 200
    assert "POST" not in response.data["actions"]
    assert {method.strip() for method in response["Allow"].split(",")} == {"GET", "HEAD", "OPTIONS"}


def test_service_key_view_exposes_deprecation_messages():
    list_view = ServiceKeyViewSet()
    detail_view = ServiceKeyViewSet()
    detail_view.kwargs = {"pk": 1}

    assert list_view.deprecated is True
    assert list_view.deprecated_message == POST_DEPRECATION_MESSAGE
    assert detail_view.deprecated_message == UPDATE_DEPRECATION_MESSAGE
    assert ServiceKeyViewSet.deprecation_warning_header_override == "HTTP POST method is no longer supported for this endpoint."


def test_service_key_warning_header_is_only_on_collection_route(admin_api_client, service_key_factory, service_cluster_eda):
    key = service_key_factory(service_cluster_eda)

    list_response = admin_api_client.get(get_relative_url("service_key-list"))
    detail_response = admin_api_client.get(get_relative_url("service_key-detail", kwargs={"pk": key.pk}))

    assert list_response["Warning"] == "HTTP POST method is no longer supported for this endpoint."
    assert "Warning" not in detail_response


def test_service_key_openapi_deprecates_only_post(admin_api_client):
    schema = admin_api_client.get(reverse("schema")).data
    service_keys_path = get_relative_url("service_key-list")
    service_key_detail_path = f"{service_keys_path}{{id}}/"

    assert service_keys_path in schema["paths"]
    assert service_key_detail_path in schema["paths"]
    operations = schema["paths"][service_keys_path]

    assert operations["post"]["deprecated"] is True
    assert operations["get"].get("deprecated") is not True

    for method in ("get", "delete", "put", "patch"):
        assert schema["paths"][service_key_detail_path][method].get("deprecated") is not True

    for method in ("post", "put", "patch"):
        request_schema = schema["paths"][service_key_detail_path if method != "post" else service_keys_path][method]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        request_schema_name = request_schema["$ref"].rsplit("/", maxsplit=1)[-1]
        request_properties = schema["components"]["schemas"][request_schema_name]["properties"]

        for field_name in ("service_cluster", "secret", "secret_length", "mark_previous_inactive", "algorithm"):
            assert request_properties[field_name]["deprecated"] is True


def test_service_key_options_marks_deprecated_create_fields(admin_api_client, service_key_factory, service_cluster_eda):
    key = service_key_factory(service_cluster_eda)
    url = get_relative_url("service_key-detail", kwargs={"pk": key.pk})

    response = admin_api_client.options(url)

    assert response.status_code == 200
    put_fields = response.data["actions"]["PUT"]
    for field_name in ("service_cluster", "secret", "secret_length", "mark_previous_inactive", "algorithm"):
        assert put_fields[field_name]["read_only"] is True
        assert put_fields[field_name]["help_text"] == "DEPRECATED: This field is no longer editable"


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
