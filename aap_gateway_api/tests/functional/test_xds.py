import pytest
from django.urls import reverse

from aap_gateway_api.models import HTTPPort


def test_xds_listener_discover_service_httpport_count(unauthenticated_api_client):
    """
    There should be as many listeners as HTTPPorts.
    """

    for port in range(8080, 8085):
        HTTPPort.objects.create(name=f"port {port}", number=port)

    url = reverse("lds")
    response = unauthenticated_api_client.post(url, data={})
    assert response.status_code == 200
    assert len(response.data['resources']) == HTTPPort.objects.all().count()


def test_xds_listener_discover_service_routes(unauthenticated_api_client, full_service_hierarchy_controller):
    url = reverse("lds")
    response = unauthenticated_api_client.post(url, data={})
    assert response.status_code == 200

    listener_routes = response.data['resources'][0]['filterChains'][0]['filters'][0]['typedConfig']['routeConfig']['virtualHosts'][0]['routes']
    sc_routes = full_service_hierarchy_controller.service_cluster.routes.all()

    assert sc_routes.count() > 0
    assert len(listener_routes) == sc_routes.count()

    for route in sc_routes:
        assert route.envoy_cluster_name in listener_routes[0]['route']['cluster']


@pytest.mark.parametrize("outlier_detection_enabled", [True, False])
def test_xds_cluster_discover_service_outlier_detection(outlier_detection_enabled, admin_api_client, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(url, {"outlier_detection_enabled": outlier_detection_enabled})
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
    assert bool("outlierDetection" in response.data['resources'][0]) == outlier_detection_enabled


def test_xds_outlier_detection_params(admin_api_client, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})

    response = admin_api_client.patch(
        url,
        {
            "outlier_detection_interval_seconds": 200,
            "outlier_detection_base_ejection_time_seconds": 500,
            "outlier_detection_max_ejection_percent": 77,
        },
    )
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200

    outlier_det = response.data['resources'][0]['outlierDetection']
    assert outlier_det['interval'] == '200s'
    assert outlier_det['baseEjectionTime'] == '500s'
    assert outlier_det['maxEjectionPercent'] == 77


@pytest.mark.parametrize("health_checks_enabled", [True, False])
def test_xds_cluster_discover_service_health_checks_enabled(health_checks_enabled, admin_api_client, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(url, {"health_checks_enabled": health_checks_enabled})
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
    assert bool("healthChecks" in response.data['resources'][0]) == health_checks_enabled


def test_xds_health_check_params(admin_api_client, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(
        url,
        {
            "health_check_timeout_seconds": 18,
            "health_check_unhealthy_threshold": 29,
            "health_check_healthy_threshold": 98,
        },
    )
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200

    health_checks = response.data['resources'][0]['healthChecks'][0]
    assert health_checks['timeout'] == '18s'
    assert health_checks['unhealthyThreshold'] == 29
    assert health_checks['healthyThreshold'] == 98


def test_xds_cluster_discover_service_route_tags(admin_api_client, full_service_hierarchy_controller, http_port_factory, randname):
    def cds_nodes():
        url = reverse("cds")
        response = admin_api_client.post(url, data={})
        assert response.status_code == 200
        endpoints = response.data['resources'][0]['loadAssignment']['endpoints'][0]['lbEndpoints']
        addresses = [x['endpoint']['address']['socketAddress']['address'] for x in endpoints]
        return addresses

    original_nodes = cds_nodes()
    assert len(original_nodes) == 1

    url = reverse("service_node-list")
    data = {"name": "Node 10.10.10.10 for Controller", "address": "10.10.10.10", "service_cluster": full_service_hierarchy_controller.service_cluster.pk}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201

    old_node_url = reverse("service_node-detail", kwargs={"pk": full_service_hierarchy_controller.service_node.pk})
    old_node_address = full_service_hierarchy_controller.service_node.address
    new_node_url = reverse("service_node-detail", kwargs={"pk": response.data['id']})
    new_node_address = response.data['address']

    route_url = reverse("route-detail", kwargs={"pk": full_service_hierarchy_controller.route.pk})

    # Sanity, the new node should be there
    nodes = cds_nodes()
    assert len(nodes) == 2
    assert new_node_address in nodes
    assert old_node_address in nodes

    # Add tags to the new node
    response = admin_api_client.patch(new_node_url, {"tags": "tag1,tag2"})
    assert response.status_code == 200

    # This shouldn't change anything, both nodes should still appear
    nodes = cds_nodes()
    assert len(nodes) == 2
    assert old_node_address in nodes
    assert new_node_address in nodes

    # Now add a node_tag to the route
    response = admin_api_client.patch(route_url, {"node_tags": "tag1"})
    assert response.status_code == 200

    # The old node should be gone
    nodes = cds_nodes()
    assert len(nodes) == 1
    assert new_node_address in nodes

    # Undo it
    response = admin_api_client.patch(route_url, {"node_tags": ""})
    assert response.status_code == 200

    # The old node should be back
    nodes = cds_nodes()
    assert len(nodes) == 2
    assert old_node_address in nodes
    assert new_node_address in nodes

    # Add a tag to the route that doesn't match any nodes
    response = admin_api_client.patch(route_url, {"node_tags": "tag3"})
    assert response.status_code == 200

    # All nodes should be gone
    with pytest.raises(KeyError):
        cds_nodes()

    # Add tag2 to old node
    response = admin_api_client.patch(old_node_url, {"tags": "tag2"})
    assert response.status_code == 200

    # Add tag2 to the route
    response = admin_api_client.patch(route_url, {"node_tags": "tag2"})
    assert response.status_code == 200

    # Both nodes should be there - (new is tagged tag1,tag2... old is tagged tag2)
    nodes = cds_nodes()
    assert len(nodes) == 2
    assert old_node_address in nodes
    assert new_node_address in nodes
