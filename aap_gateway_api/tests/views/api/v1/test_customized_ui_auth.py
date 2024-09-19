import pytest
from ansible_base.lib.utils.response import get_relative_url


def get_ui_auth(client):
    url = get_relative_url("ui_auth")
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.data


@pytest.mark.django_db
def test_default_urls_no_services(unauthenticated_api_client):
    data = get_ui_auth(unauthenticated_api_client)
    assert data["legacy_controller_sso_url"] == ""
    assert data["legacy_automation_hub_sso_url"] == ""


@pytest.mark.django_db
def test_default_urls_services_configured(
    unauthenticated_api_client,
    service_api_route_hub,
    service_api_route_controller,
    service_node_controller,
    service_node_hub,
):
    data = get_ui_auth(unauthenticated_api_client)
    assert service_api_route_controller.service_cluster.nodes.first().address in data["legacy_controller_sso_url"]
    assert service_api_route_hub.service_cluster.nodes.first().address in data["legacy_automation_hub_sso_url"]


@pytest.mark.django_db
def test_urls_custom(unauthenticated_api_client, set_preference):
    data = get_ui_auth(unauthenticated_api_client)
    assert data["legacy_controller_sso_url"] == ""
    assert data["legacy_automation_hub_sso_url"] == ""

    set_preference("legacy_sso", "CONTROLLER_SSO_URL", "https://ctr.example.com")
    set_preference("legacy_sso", "AUTOMATION_HUB_SSO_URL", "https:/hub.example.com")

    data = get_ui_auth(unauthenticated_api_client)

    assert data["legacy_controller_sso_url"] == "https://ctr.example.com"
    assert data["legacy_automation_hub_sso_url"] == "https:/hub.example.com"
