"""Performance tests for xDS REST control plane views.

Verifies that CDS/LDS/SDS generation scales correctly with
prefetch_related optimizations and response caching.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from aap_gateway_api.models import AdditionalRoute, HTTPPort, Route, ServiceAPIRoute, ServiceNode
from aap_gateway_api.models.service_cluster import ServiceCluster
from aap_gateway_api.models.service_type import ServiceType
from aap_gateway_api.models.ui_plugin_route import UIPluginRoute
from aap_gateway_api.views.api.envoy.rest_control_plane import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, invalidate_xds_cache


def _create_service_hierarchy(cluster_count, nodes_per_cluster, routes_per_cluster):
    """Create clusters, nodes, and routes for scaling tests."""
    port = HTTPPort.objects.create(name="perf-port", number=9999)
    svc_type, _ = ServiceType.objects.get_or_create(
        name="perf-controller",
        defaults={"ping_url": "/ping/"},
    )

    clusters = []
    for c in range(cluster_count):
        cluster = ServiceCluster.objects.create(
            name=f"perf-cluster-{c:03d}",
            service_type=svc_type,
        )
        for n in range(nodes_per_cluster):
            ServiceNode.objects.create(
                name=f"perf-node-{c:03d}-{n:03d}",
                service_cluster=cluster,
                address=f"10.0.{c}.{n + 1}",
            )
        for r in range(routes_per_cluster):
            Route.objects.create(
                name=f"perf-route-{c:03d}-{r:03d}",
                http_port=port,
                service_cluster=cluster,
                service_port=8080 + r,
                is_service_https=False,
                service_path=f"/svc-{c}-{r}/",
                gateway_path=f"/gw-{c}-{r}/",
                enable_gateway_auth=True,
            )
        clusters.append(cluster)

    return port, clusters


@pytest.mark.django_db
def test_cds_query_count_bounded(unauthenticated_api_client):
    """CDS query count should not scale with route or node count.

    With prefetch_related, all nodes and service types are loaded in
    bulk queries rather than per-route lazy loads.
    """
    _create_service_hierarchy(cluster_count=5, nodes_per_cluster=10, routes_per_cluster=4)

    url = reverse("cds")
    with CaptureQueriesContext(connection) as ctx:
        response = unauthenticated_api_client.post(url, data={})

    assert response.status_code == 200
    assert len(response.data["resources"]) == 20
    # Without prefetch: ~20 routes x 1 node query each = 20+ queries
    # With prefetch: route query + prefetch nodes + prefetch service_type +
    #   max_timeouts aggregate = ~5 queries
    assert len(ctx.captured_queries) < 10, (
        f"CDS used {len(ctx.captured_queries)} queries for 20 routes — "
        f"expected <10 with prefetch_related. "
        f"Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_lds_query_count_bounded(unauthenticated_api_client):
    """LDS query count should not scale with route count.

    With prefetch_related and hoisted gateway lookup, all routes and
    their service clusters are loaded in bulk.
    """
    port, _ = _create_service_hierarchy(cluster_count=3, nodes_per_cluster=5, routes_per_cluster=5)

    url = reverse("lds")
    with CaptureQueriesContext(connection) as ctx:
        response = unauthenticated_api_client.post(url, data={})

    assert response.status_code == 200
    assert len(response.data["resources"]) > 0
    # Without prefetch: 1 port query + 15 route queries (routes.all per port) +
    #   15x2 gateway lookups = 45+ queries
    # With prefetch + hoisted gateway lookup: port query + prefetch routes +
    #   prefetch service_cluster + prefetch service_type + gateway lookup = ~7
    assert len(ctx.captured_queries) < 15, (
        f"LDS used {len(ctx.captured_queries)} queries — expected <15 with prefetch_related. Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_cds_cache_hit_zero_queries(unauthenticated_api_client):
    """Second CDS call should serve from cache with zero DB queries."""
    _create_service_hierarchy(cluster_count=2, nodes_per_cluster=3, routes_per_cluster=2)
    url = reverse("cds")

    first_response = unauthenticated_api_client.post(url, data={})
    assert first_response.status_code == 200

    with CaptureQueriesContext(connection) as ctx:
        second_response = unauthenticated_api_client.post(url, data={})

    assert second_response.status_code == 200
    assert second_response.data == first_response.data
    assert len(ctx.captured_queries) == 0, (
        f"Cache hit should use 0 queries, got {len(ctx.captured_queries)}. Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_lds_cache_hit_zero_queries(unauthenticated_api_client):
    """Second LDS call should serve from cache with zero DB queries."""
    _create_service_hierarchy(cluster_count=2, nodes_per_cluster=3, routes_per_cluster=2)
    url = reverse("lds")

    first_response = unauthenticated_api_client.post(url, data={})
    assert first_response.status_code == 200

    with CaptureQueriesContext(connection) as ctx:
        second_response = unauthenticated_api_client.post(url, data={})

    assert second_response.status_code == 200
    assert second_response.data == first_response.data
    assert len(ctx.captured_queries) == 0, (
        f"Cache hit should use 0 queries, got {len(ctx.captured_queries)}. Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_sds_cache_hit_zero_queries(unauthenticated_api_client):
    """Second SDS call should serve from cache with zero DB queries."""
    from aap_gateway_api.models.ca_certificate import CACertificate

    CACertificate.objects.create(
        name="perf-ca",
        pem_data="-----BEGIN CERTIFICATE-----\nMIItest\n-----END CERTIFICATE-----",
        sha256="abc123",
    )
    url = reverse("sds")

    first_response = unauthenticated_api_client.post(url, data={})
    assert first_response.status_code == 200

    with CaptureQueriesContext(connection) as ctx:
        second_response = unauthenticated_api_client.post(url, data={})

    assert second_response.status_code == 200
    assert second_response.data == first_response.data
    assert len(ctx.captured_queries) == 0, (
        f"Cache hit should use 0 queries, got {len(ctx.captured_queries)}. Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


def _populate_and_warm_cds_lds(client):
    """Create minimal data and warm both CDS and LDS caches."""
    port, clusters = _create_service_hierarchy(cluster_count=1, nodes_per_cluster=1, routes_per_cluster=1)
    cds_url = reverse("cds")
    lds_url = reverse("lds")
    client.post(cds_url, data={})
    client.post(lds_url, data={})
    return port, clusters


def _assert_cache_invalidated(client, cds=True, lds=True):
    """Assert that cached endpoints now trigger DB queries (cache was busted)."""
    if cds:
        with CaptureQueriesContext(connection) as ctx:
            client.post(reverse("cds"), data={})
        assert len(ctx.captured_queries) > 0, "CDS cache should have been invalidated"
    if lds:
        with CaptureQueriesContext(connection) as ctx:
            client.post(reverse("lds"), data={})
        assert len(ctx.captured_queries) > 0, "LDS cache should have been invalidated"


@pytest.mark.django_db
def test_cache_invalidated_on_route_save(unauthenticated_api_client):
    """Modifying a base Route should invalidate both CDS and LDS caches."""
    _populate_and_warm_cds_lds(unauthenticated_api_client)
    route = Route.objects.filter(name__startswith="perf-").first()
    route.service_path = "/updated/"
    route.save()
    _assert_cache_invalidated(unauthenticated_api_client)


@pytest.mark.django_db
def test_cache_invalidated_on_additional_route_save(unauthenticated_api_client):
    """Saving an AdditionalRoute should invalidate CDS and LDS caches."""
    port, clusters = _populate_and_warm_cds_lds(unauthenticated_api_client)
    AdditionalRoute.objects.create(
        name="perf-additional-route",
        http_port=port,
        service_cluster=clusters[0],
        service_port=9090,
        is_service_https=False,
        service_path="/additional/",
        gateway_path="/additional/",
    )
    _assert_cache_invalidated(unauthenticated_api_client)


@pytest.mark.django_db
def test_cache_invalidated_on_service_api_route_save(unauthenticated_api_client):
    """Saving a ServiceAPIRoute should invalidate CDS and LDS caches."""
    port, clusters = _populate_and_warm_cds_lds(unauthenticated_api_client)
    HTTPPort.objects.filter(pk=port.pk).update(is_api_port=True)
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    unauthenticated_api_client.post(reverse("cds"), data={})
    unauthenticated_api_client.post(reverse("lds"), data={})
    ServiceAPIRoute.objects.create(
        name="perf-api-route",
        http_port=port,
        service_cluster=clusters[0],
        service_port=9091,
        is_service_https=False,
        service_path="/api/perf/",
        api_slug="perf",
    )
    _assert_cache_invalidated(unauthenticated_api_client)


@pytest.mark.django_db
def test_cache_invalidated_on_ui_plugin_route_save(unauthenticated_api_client):
    """Saving a UIPluginRoute should invalidate CDS and LDS caches."""
    port, clusters = _populate_and_warm_cds_lds(unauthenticated_api_client)
    UIPluginRoute.objects.create(
        name="perf-ui-plugin-route",
        http_port=port,
        service_cluster=clusters[0],
        service_port=9092,
        is_service_https=False,
        service_path="/plugin/",
        gateway_path="/plugin/",
        ui_plugin_path="test-plugin",
    )
    _assert_cache_invalidated(unauthenticated_api_client)


@pytest.mark.django_db
def test_cache_invalidated_on_service_node_save(unauthenticated_api_client):
    """Saving a ServiceNode should invalidate CDS cache."""
    port, clusters = _populate_and_warm_cds_lds(unauthenticated_api_client)
    ServiceNode.objects.create(
        name="perf-extra-node",
        service_cluster=clusters[0],
        address="10.99.99.1",
    )
    _assert_cache_invalidated(unauthenticated_api_client, cds=True, lds=False)


@pytest.mark.django_db
def test_cache_invalidated_on_service_cluster_save(unauthenticated_api_client):
    """Saving a ServiceCluster should invalidate CDS and LDS caches."""
    _populate_and_warm_cds_lds(unauthenticated_api_client)
    cluster = ServiceCluster.objects.filter(name__startswith="perf-").first()
    cluster.outlier_detection_enabled = True
    cluster.save()
    _assert_cache_invalidated(unauthenticated_api_client)


@pytest.mark.django_db
def test_cache_invalidated_on_ca_certificate_save(unauthenticated_api_client):
    """Saving a CACertificate should invalidate SDS cache."""
    from aap_gateway_api.models.ca_certificate import CACertificate

    url = reverse("sds")
    unauthenticated_api_client.post(url, data={})

    CACertificate.objects.create(
        name="perf-ca-invalidation",
        pem_data="-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        sha256="invalidation-test",
    )

    with CaptureQueriesContext(connection) as ctx:
        unauthenticated_api_client.post(url, data={})
    assert len(ctx.captured_queries) > 0, "SDS cache should have been invalidated"
