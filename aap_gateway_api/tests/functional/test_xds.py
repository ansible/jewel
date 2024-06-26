import pytest
from django.urls import reverse


def test_xds_listener_discover_service(unauthenticated_api_client):
    url = reverse("lds")
    response = unauthenticated_api_client.post(url, data={})
    assert response.status_code == 200


def test_xds_cluster_discover_service(admin_api_client):
    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200


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

    response = admin_api_client.patch(url, {"outlier_detection_enabled": True})
    assert response.status_code == 200
    response = admin_api_client.patch(url, {"outlier_detection_interval_seconds": 20})
    assert response.status_code == 200
    response = admin_api_client.patch(url, {"outlier_detection_base_ejection_time_seconds": 50})
    assert response.status_code == 200
    response = admin_api_client.patch(url, {"outlier_detection_max_ejection_percent": 50})


@pytest.mark.parametrize("health_checks", [True, False])
def test_xds_cluster_discover_service_health_checks_enabled(health_checks, admin_api_client, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(url, {"health_checks_enabled": health_checks})
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
    assert bool("healthChecks" in response.data['resources'][0]) == health_checks


@pytest.mark.parametrize("health_checks_enabled", [True])
def test_xds_cluster_discover_service_health_check_params(admin_api_client, health_checks_enabled, full_service_hierarchy_controller):
    url = reverse("service_cluster-detail", kwargs={"pk": full_service_hierarchy_controller.service_cluster.pk})
    response = admin_api_client.patch(url, {"health_checks_enabled": health_checks_enabled})
    assert response.status_code == 200
    response = admin_api_client.patch(url, data={"health_check_timeout_seconds": 10})
    assert response.status_code == 200
    response = admin_api_client.patch(url, data={"health_check_unhealthy_threshold": 40})
    assert response.status_code == 200
    response = admin_api_client.patch(url, data={"health_check_healthy_threshold": 100})
    assert response.status_code == 200

    url = reverse("cds")
    response = admin_api_client.post(url, data={})
    assert response.status_code == 200
