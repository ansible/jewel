from unittest import mock
from unittest.mock import Mock

from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import ServiceNode


def test_status_unauthenticated(unauthenticated_api_client):
    """
    When not authenticated, the status endpoint should not be accessible.
    """
    url = get_relative_url("status-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


def test_status_nonadmin(user_api_client):
    """
    The user must be an admin to access the status endpoint.
    """
    url = get_relative_url("status-view")
    response = user_api_client.get(url)
    assert response.status_code == 403


def test_status_no_services(admin_api_client):
    """
    The status endpoint should return a 200 response.

    By default there are no services, so the status should be "good" and
    there should be no services listed.
    """
    url = get_relative_url("status-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert response.data["services"] == {}


def test_status_route_with_no_nodes(admin_api_client, additional_route_controller):
    url = get_relative_url("status-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    assert response.data["services"]["controller"] == {}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_500(get, admin_api_client, full_service_hierarchy_controller):
    get.return_value = Mock(status_code=500, text="test")
    url = get_relative_url("status-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    assert response.data["services"]["controller"][node_id]["status"] == "Failed"
    assert response.data["services"]["controller"][node_id]["response_code"] == 500
    assert response.data["services"]["controller"][node_id]["body"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_200(get, admin_api_client, full_service_hierarchy_controller):
    get.return_value = Mock(status_code=200, json=lambda: {"test": "test"})
    url = get_relative_url("status-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    assert response.data["services"]["controller"][node_id]["status"] == "Good"
    assert response.data["services"]["controller"][node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_exception(get, admin_api_client, full_service_hierarchy_controller):
    get.side_effect = Exception("test")
    url = get_relative_url("status-view")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    assert response.data["services"]["controller"][node_id]["status"] == "Failed"
    assert response.data["services"]["controller"][node_id]["exception"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_routes_same_service_cluster(get, admin_api_client, full_service_hierarchy_controller, http_port_factory, randname):
    """
    Test that the status endpoint can handle multiple routes to the same service cluster.
    """
    get.return_value = Mock(status_code=200, json=lambda: {"test": "test"})

    port = http_port_factory()
    route_copy = full_service_hierarchy_controller.route
    route_copy.pk = None
    route_copy.id = None
    route_copy.http_port = port
    route_copy.name = randname('Different Route')
    route_copy.save()

    url = get_relative_url("status-view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    assert response.data["services"]["controller"][node_id]["status"] == "Good"
    assert response.data["services"]["controller"][node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_multiple_service_nodes(get, admin_api_client, full_service_hierarchy_controller):
    """
    Test that the status endpoint can handle multiple service nodes pointing to the same service cluster.
    """
    get.return_value = Mock(status_code=200, json=lambda: {"test": "test"})

    new_service_node = ServiceNode.objects.create(
        name="Node 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )
    another_service_node = ServiceNode.objects.create(
        name="Node 127.0.0.100",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.100",
    )

    url = get_relative_url("status-view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert 'controller' in response.data["services"]
    controller = response.data["services"]["controller"]

    assert len(controller) == 3

    node_id_1 = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    node_id_2 = f"{new_service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    node_id_3 = f"{another_service_node.address}:{full_service_hierarchy_controller.route.service_port}"

    for node_id in (node_id_1, node_id_2, node_id_3):
        assert controller[node_id]["status"] == "Good"
        assert controller[node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_hierarchies(get, admin_api_client, full_service_hierarchy_controller, full_service_hierarchy_hub):
    """
    Test that the status endpoint can handle multiple complete service hierarchies.
    """
    get.return_value = Mock(status_code=200, json=lambda: {"test": "test"})

    url = get_relative_url("status-view")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert response.data["status"] == "good"
    assert "controller" in response.data["services"]
    assert "hub" in response.data["services"]

    node_id_controller = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
    assert response.data["services"]["controller"][node_id_controller]["status"] == "Good"
    assert response.data["services"]["controller"][node_id_controller]["response"] == {"test": "test"}

    node_id_hub = f"{full_service_hierarchy_hub.service_node.address}:{full_service_hierarchy_hub.route.service_port}"
    assert response.data["services"]["hub"][node_id_hub]["status"] == "Good"
    assert response.data["services"]["hub"][node_id_hub]["response"] == {"test": "test"}
