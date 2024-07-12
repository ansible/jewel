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
