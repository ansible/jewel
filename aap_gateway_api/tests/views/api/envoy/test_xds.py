import pytest
from django.urls import reverse

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceNode


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
    listener_routes.pop(0)  # Discard /up static route
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


def test_xds_cluster_discover_service_sni(admin_api_client, full_service_hierarchy_controller):
    cds_url = reverse("cds")

    route_url = reverse("route-detail", kwargs={"pk": full_service_hierarchy_controller.route.pk})
    admin_api_client.patch(route_url, {"is_service_https": True})

    response = admin_api_client.post(cds_url, data={})
    assert response.status_code == 200
    assert 'sni' not in response.data['resources'][0]['transportSocket']['typedConfig']

    cluster_url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(cluster_url, {"upstream_hostname": "ebay.com"})
    assert response.status_code == 200

    response = admin_api_client.post(cds_url, data={})
    assert response.status_code == 200
    assert response.data['resources'][0]['transportSocket']['typedConfig']['sni'] == "ebay.com"


def test_xds_cluster_discover_service_dns(admin_api_client, full_service_hierarchy_controller):
    cluster_url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(cluster_url, {"dns_discovery_type": "LOGICAL_DNS", "dns_lookup_family": "V4_ONLY"})
    assert response.status_code == 200

    cds_url = reverse("cds")
    response = admin_api_client.post(cds_url, data={})
    assert response.status_code == 200
    assert response.data["resources"][0]["type"] == "LOGICAL_DNS"
    assert response.data["resources"][0]["dnsLookupFamily"] == "V4_ONLY"


def test_lds_listener_discover_service_service_type_auth_type(admin_api_client, full_service_hierarchy_controller):
    cluster_url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(cluster_url, {"service_type": 3, "auth_type": "TOKEN"})
    assert response.status_code == 200

    lds_url = reverse("lds")
    response = admin_api_client.post(lds_url, data={})
    assert response.status_code == 200

    route_config = response.data["resources"][0]["filterChains"][0]["filters"][0]["typedConfig"]["routeConfig"]["virtualHosts"][0]["routes"][1]
    assert route_config["typedPerFilterConfig"]["envoy.filters.http.ext_authz"]["checkSettings"]["contextExtensions"]["service_type"] == "hub"
    assert route_config["typedPerFilterConfig"]["envoy.filters.http.ext_authz"]["checkSettings"]["contextExtensions"]["auth_type"] == "TOKEN"


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


def get_lds_routes(admin_api_client):
    routes = {}
    url = reverse("lds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
    filter = response.data['resources'][0]["filterChains"][0]["filters"][0]
    for route in filter["typedConfig"]["routeConfig"]["virtualHosts"][0]["routes"]:
        if route["match"]["prefix"] == "/up":
            # Avoid envoy self-hosted /up route
            continue
        routes[route["match"]["prefix"]] = route["route"]["cluster"]
    return routes


def get_cds_clusters(admin_api_client):
    clusters = {}
    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
    for cluster in response.data['resources']:
        name = cluster['loadAssignment']["clusterName"]
        endpoints = cluster['loadAssignment']['endpoints'][0]['lbEndpoints']
        addresses = [x['endpoint']['address']['socketAddress']['address'] for x in endpoints]
        clusters[name] = addresses
    return clusters


def test_xds_cluster_names(admin_api_client, service_cluster_eda, http_api_port_factory, randname):
    port = http_api_port_factory()
    service_port = "8000"

    route = AdditionalRoute.objects.create(
        name=randname("webhook"),
        http_port=port,
        service_cluster=service_cluster_eda,
        service_port=service_port,
        is_service_https=False,
        service_path="/eda-webhooks/",
        gateway_path="/eda-webhooks/",
        node_tags="",
    )

    service = ServiceAPIRoute.objects.create(
        name=randname("api"),
        http_port=port,
        service_cluster=service_cluster_eda,
        service_port=service_port,
        is_service_https=False,
        service_path="/api/eda/",
        api_slug="eda",
        node_tags="",
    )

    node_a = ServiceNode.objects.create(name=randname("eda_node"), service_cluster=service_cluster_eda, address="eda_a", tags="a")
    node_b = ServiceNode.objects.create(name=randname("eda_node"), service_cluster=service_cluster_eda, address="eda_b", tags="b")

    cluster_base_name = f"cluster-{service_cluster_eda.pk}-{service_port}-nodes:"

    # Check that routes with no tag both select the same cluster with all nodes
    routes = get_lds_routes(admin_api_client)
    clusters = get_cds_clusters(admin_api_client)
    assert routes["/api/eda/"] == routes["/eda-webhooks/"]
    assert set(clusters[cluster_base_name + "*"]) == set([node_a.address, node_b.address])
    assert len(clusters) == 1

    # Check that routes with unique tag combos create distinct clusters
    route.node_tags = "a"
    route.save()
    service.node_tags = "b"
    service.save()

    routes = get_lds_routes(admin_api_client)
    clusters = get_cds_clusters(admin_api_client)
    assert routes["/api/eda/"] == cluster_base_name + "b"
    assert routes["/eda-webhooks/"] == cluster_base_name + "a"
    assert set(clusters[cluster_base_name + "b"]) == set([node_b.address])
    assert set(clusters[cluster_base_name + "a"]) == set([node_a.address])
    assert len(clusters) == 2

    # Check that the order of the tags doesn't matter
    route.node_tags = "a,b"
    route.save()
    service.node_tags = "b,a"
    service.save()

    routes = get_lds_routes(admin_api_client)
    clusters = get_cds_clusters(admin_api_client)
    assert routes["/api/eda/"] == cluster_base_name + "a,b"
    assert routes["/eda-webhooks/"] == cluster_base_name + "a,b"
    assert routes["/api/eda/"] == routes["/eda-webhooks/"]
    assert set(clusters[cluster_base_name + "a,b"]) == set([node_a.address, node_b.address])
    assert len(clusters) == 1
