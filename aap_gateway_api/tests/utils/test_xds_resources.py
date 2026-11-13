"""Unit tests for the shared xDS resource collectors (no HTTP)."""

import pytest
from django.core.cache import cache

from aap_gateway_api.utils.xds_resources import (
    XDS_CACHE_KEY_CDS,
    XDS_CACHE_KEY_LDS,
    XDS_CACHE_KEY_SDS,
    collect_clusters,
    collect_listeners,
    collect_secrets,
    invalidate_xds_cache,
)


@pytest.fixture(autouse=True)
def _clear_xds_cache():
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    yield
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


@pytest.mark.django_db
def test_collect_clusters_round_trips_through_cache(full_service_hierarchy_controller):
    first = collect_clusters()
    assert cache.get(XDS_CACHE_KEY_CDS) is not None
    second = collect_clusters()
    assert second.version == first.version


@pytest.mark.django_db
def test_collect_listeners_round_trips_through_cache(full_service_hierarchy_controller):
    first = collect_listeners()
    assert cache.get(XDS_CACHE_KEY_LDS) is not None
    second = collect_listeners()
    assert second.version == first.version


@pytest.mark.django_db
def test_collect_secrets_round_trips_through_cache():
    first = collect_secrets()
    # SDS always caches, even when there are no CA certificates.
    assert cache.get(XDS_CACHE_KEY_SDS) is not None
    second = collect_secrets()
    assert second.version == first.version


@pytest.mark.django_db
def test_digest_stable_across_rebuilds(full_service_hierarchy_controller):
    first = collect_clusters()
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    second = collect_clusters()
    assert second.version == first.version


@pytest.mark.django_db
def test_digest_changes_when_route_changes(full_service_hierarchy_controller):
    first = collect_clusters()
    route = full_service_hierarchy_controller.route
    # gateway_path only affects LDS; is_service_https changes the cluster's
    # transport socket, which is part of the CDS resources.
    route.is_service_https = not route.is_service_https
    route.save()  # fires the signal that invalidates the cache
    # transaction.on_commit callbacks (used by the invalidation signals) do
    # not fire inside pytest-django's wrapped transaction, so invalidate
    # explicitly to simulate the signal's on_commit effect.
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    second = collect_clusters()
    assert second.version != first.version


@pytest.mark.django_db
def test_collect_clusters_caching_rule():
    # The no-cache-empty rule, expressed invariantly because post_migrate
    # may seed default gateway data in the test DB:
    rs = collect_clusters()
    if rs.resources == []:
        assert cache.get(XDS_CACHE_KEY_CDS) is None
    else:
        assert cache.get(XDS_CACHE_KEY_CDS) is not None
