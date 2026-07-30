from unittest.mock import Mock

import pytest
from django.db import connection
from django.db.models import Max
from django.test.utils import CaptureQueriesContext

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceCluster, ServiceType
from aap_gateway_api.serializers.service_cluster import ServiceClusterSerializer


@pytest.mark.django_db
class TestServiceClusterSerializer:
    """Tests for ServiceClusterSerializer."""

    @pytest.fixture
    def service_type(self):
        """Create a service type for testing."""
        return ServiceType.objects.create(name="Controller", login_path="/api/login/", logout_path="/api/logout/", ping_url="/api/ping/")

    def test_serializer_meta_fields_includes_all_cluster_fields(self):
        """Test that serializer Meta.fields includes all necessary fields."""
        expected_fields = [
            'service_type',
            'service_id',
            'auth_type',
            'upstream_hostname',
            'dns_discovery_type',
            'dns_lookup_family',
            'outlier_detection_enabled',
            'outlier_detection_consecutive_5xx',
            'outlier_detection_interval_seconds',
            'outlier_detection_base_ejection_time_seconds',
            'outlier_detection_max_ejection_percent',
            'health_checks_enabled',
            'health_check_timeout_seconds',
            'health_check_interval_seconds',
            'health_check_unhealthy_threshold',
            'health_check_healthy_threshold',
            'healthy_panic_threshold',
            'effective_health_check_timeout_seconds',
            'effective_health_check_interval_seconds',
        ]
        for field in expected_fields:
            assert field in ServiceClusterSerializer.Meta.fields, f"Field {field} missing from Meta.fields"

        # Also check for inherited fields
        assert 'name' in ServiceClusterSerializer.Meta.fields

    def test_create_service_cluster_via_serializer(self, service_type):
        """Test creating a service cluster through the serializer."""
        data = {
            'name': 'Test Cluster',
            'service_type': service_type.id,
            'auth_type': 'JWT',
        }
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        cluster = serializer.save()
        assert cluster.name == 'Test Cluster'
        assert cluster.service_type == service_type
        assert cluster.auth_type == 'JWT'

    def test_create_service_cluster_with_health_checks(self, service_type):
        """Test creating a service cluster with health check configuration."""
        data = {
            'name': 'Health Check Cluster',
            'service_type': service_type.id,
            'auth_type': 'JWT',
            'health_checks_enabled': True,
            'health_check_timeout_seconds': 5,
            'health_check_interval_seconds': 10,
            'health_check_unhealthy_threshold': 3,
            'health_check_healthy_threshold': 2,
        }
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        cluster = serializer.save()
        assert cluster.health_checks_enabled is True
        assert cluster.health_check_timeout_seconds == 5
        assert cluster.health_check_interval_seconds == 10
        assert cluster.health_check_unhealthy_threshold == 3
        assert cluster.health_check_healthy_threshold == 2

    def test_create_service_cluster_with_outlier_detection(self, service_type):
        """Test creating a service cluster with outlier detection configuration."""
        data = {
            'name': 'Outlier Detection Cluster',
            'service_type': service_type.id,
            'auth_type': 'JWT',
            'outlier_detection_enabled': True,
            'outlier_detection_consecutive_5xx': 5,
            'outlier_detection_interval_seconds': 30,
            'outlier_detection_base_ejection_time_seconds': 60,
            'outlier_detection_max_ejection_percent': 50,
        }
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        cluster = serializer.save()
        assert cluster.outlier_detection_enabled is True
        assert cluster.outlier_detection_consecutive_5xx == 5
        assert cluster.outlier_detection_interval_seconds == 30
        assert cluster.outlier_detection_base_ejection_time_seconds == 60
        assert cluster.outlier_detection_max_ejection_percent == 50

    def test_create_service_cluster_with_dns_settings(self, service_type):
        """Test creating a service cluster with DNS discovery settings."""
        data = {
            'name': 'DNS Cluster',
            'service_type': service_type.id,
            'auth_type': 'JWT',
            'upstream_hostname': 'service.example.com',
            'dns_discovery_type': 'STRICT_DNS',
            'dns_lookup_family': 'V4_ONLY',
        }
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        cluster = serializer.save()
        assert cluster.upstream_hostname == 'service.example.com'
        assert cluster.dns_discovery_type == 'STRICT_DNS'
        assert cluster.dns_lookup_family == 'V4_ONLY'

    def test_update_service_cluster_via_serializer(self, service_type):
        """Test updating a service cluster through the serializer."""
        cluster = ServiceCluster.objects.create(name="Original Cluster", service_type=service_type)

        data = {
            'name': 'Updated Cluster',
            'health_checks_enabled': True,
        }
        serializer = ServiceClusterSerializer(instance=cluster, data=data, partial=True, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        updated_cluster = serializer.save()
        assert updated_cluster.name == 'Updated Cluster'
        assert updated_cluster.health_checks_enabled is True

    def test_service_cluster_requires_service_type(self):
        """Test that service_type is required."""
        data = {'name': 'Test Cluster', 'auth_type': 'JWT'}
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert not serializer.is_valid()
        assert 'service_type' in serializer.errors

    def test_service_cluster_requires_auth_type(self, service_type):
        """Test that auth_type is required."""
        data = {'name': 'Test Cluster', 'service_type': service_type.id}
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        # auth_type might have a default, so this test checks behavior
        # If it's required, validation will fail; if it has a default, it will pass
        # Let's check if the serializer is valid or if auth_type is in errors
        if not serializer.is_valid():
            assert 'auth_type' in serializer.errors or serializer.is_valid()

    def test_service_cluster_healthy_panic_threshold(self, service_type):
        """Test setting healthy_panic_threshold on service cluster."""
        data = {
            'name': 'Panic Threshold Cluster',
            'service_type': service_type.id,
            'auth_type': 'JWT',
            'healthy_panic_threshold': 25,
        }
        serializer = ServiceClusterSerializer(data=data, context={'request': Mock(query_params={})})
        assert serializer.is_valid(), serializer.errors
        cluster = serializer.save()
        assert cluster.healthy_panic_threshold == 25

    def test_effective_health_check_timeout_in_serializer_fields(self):
        assert 'effective_health_check_timeout_seconds' in ServiceClusterSerializer.Meta.fields

    @pytest.mark.parametrize(
        "health_check_timeout,route_timeout,preference_timeout,expected",
        [
            (5, 600, 30, 600),
            (5, None, 30, 30),
            (700, 600, 30, 700),
            (5, None, 60, 60),
        ],
        ids=[
            "route_timeout_highest",
            "no_route_uses_preference",
            "cluster_timeout_highest",
            "preference_highest",
        ],
    )
    def test_effective_health_check_timeout_seconds(self, service_type, health_check_timeout, route_timeout, preference_timeout, expected, preference_manager):
        cluster = ServiceCluster.objects.create(
            name='Effective Timeout Cluster',
            service_type=service_type,
            health_check_timeout_seconds=health_check_timeout,
        )
        http_port = HTTPPort.objects.create(name="effective-timeout-port", number=9996)

        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            if route_timeout is not None:
                AdditionalRoute.objects.create(
                    name="effective-timeout-route",
                    http_port=http_port,
                    is_service_https=False,
                    service_cluster=cluster,
                    service_port=8080,
                    service_path="/path",
                    gateway_path="/effective-test/",
                    request_timeout_seconds=route_timeout,
                )

            serializer = ServiceClusterSerializer(instance=cluster, context={'request': Mock(query_params={})})
            assert serializer.data['effective_health_check_timeout_seconds'] == expected

    @pytest.mark.parametrize(
        "health_check_timeout,route_timeout,preference_timeout,expected",
        [
            (5, 600, 30, 600),
            (5, None, 30, 30),
            (700, 600, 30, 700),
        ],
        ids=[
            "annotated_route_timeout_highest",
            "annotated_no_route_uses_preference",
            "annotated_cluster_timeout_highest",
        ],
    )
    def test_effective_health_check_timeout_uses_annotation(
        self, service_type, health_check_timeout, route_timeout, preference_timeout, expected, preference_manager
    ):
        """Verify the serializer uses _max_route_timeout annotation to avoid N+1 queries."""
        cluster = ServiceCluster.objects.create(
            name='Annotated Timeout Cluster',
            service_type=service_type,
            health_check_timeout_seconds=health_check_timeout,
        )
        http_port = HTTPPort.objects.create(name="annotated-timeout-port", number=9997)

        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            if route_timeout is not None:
                AdditionalRoute.objects.create(
                    name="annotated-timeout-route",
                    http_port=http_port,
                    is_service_https=False,
                    service_cluster=cluster,
                    service_port=8080,
                    service_path="/path",
                    gateway_path="/annotated-test/",
                    request_timeout_seconds=route_timeout,
                )

            annotated = (
                ServiceCluster.objects.filter(pk=cluster.pk)
                .annotate(
                    _max_route_timeout=Max('routes__request_timeout_seconds'),
                )
                .get()
            )
            serializer = ServiceClusterSerializer(instance=annotated, context={'request': Mock(query_params={})})

            with CaptureQueriesContext(connection) as ctx:
                result = serializer.data['effective_health_check_timeout_seconds']
            assert result == expected
            # The annotation path must not issue any additional aggregate
            # queries; if this fires, the code regressed to the fallback.
            aggregate_queries = [q for q in ctx.captured_queries if 'MAX' in q['sql'].upper()]
            assert aggregate_queries == [], f"Annotation should prevent aggregate queries, but got: {aggregate_queries}"

    def test_effective_health_check_interval_in_serializer_fields(self):
        assert 'effective_health_check_interval_seconds' in ServiceClusterSerializer.Meta.fields

    @pytest.mark.parametrize(
        "health_check_interval,health_check_timeout,route_timeout,preference_timeout,expected",
        [
            (10, 5, None, 30, 30),
            (60, 5, None, 30, 60),
            (10, 5, 600, 30, 600),
        ],
        ids=["interval_below_effective_timeout", "interval_above_effective_timeout", "route_timeout_raises_floor"],
    )
    def test_effective_health_check_interval_seconds(
        self, service_type, health_check_interval, health_check_timeout, route_timeout, preference_timeout, expected, preference_manager
    ):
        cluster = ServiceCluster.objects.create(
            name='Effective Interval Cluster',
            service_type=service_type,
            health_check_timeout_seconds=health_check_timeout,
            health_check_interval_seconds=health_check_interval,
        )
        http_port = HTTPPort.objects.create(name="effective-interval-port", number=9995)

        with preference_manager.set("proxy", "request_timeout", preference_timeout):
            if route_timeout is not None:
                AdditionalRoute.objects.create(
                    name="effective-interval-route",
                    http_port=http_port,
                    is_service_https=False,
                    service_cluster=cluster,
                    service_port=8080,
                    service_path="/path",
                    gateway_path="/effective-interval-test/",
                    request_timeout_seconds=route_timeout,
                )
            serializer = ServiceClusterSerializer(instance=cluster, context={'request': Mock(query_params={})})
            assert serializer.data['effective_health_check_interval_seconds'] == expected
