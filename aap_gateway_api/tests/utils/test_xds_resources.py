"""Unit tests for the shared xDS resource collectors (no HTTP)."""

from unittest import mock

import pytest
from django.core.cache import cache

from aap_gateway_api.utils import xds_resources
from aap_gateway_api.utils.xds_resources import (
    XDS_CACHE_KEY_CDS,
    XDS_CACHE_KEY_LDS,
    XDS_CACHE_KEY_SDS,
    XDS_CACHE_TIMEOUT,
    XDS_LEGACY_CACHE_KEYS,
    ResourceSet,
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


def test_cache_keys_do_not_collide_with_legacy_keys():
    # Pre-ADS gateway versions cached MessageToDict dicts under "xds:cds" etc.
    # on the same shared redis; ResourceSets must never share those keys.
    current = {XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS}
    assert set(XDS_LEGACY_CACHE_KEYS.values()) == {"xds:cds", "xds:lds", "xds:sds"}
    assert current.isdisjoint(XDS_LEGACY_CACHE_KEYS.values())


def test_invalidate_also_deletes_legacy_counterpart():
    cache.set("xds:cds", {"clusters": []})
    cache.set("xds:lds", {"listeners": []})
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    assert cache.get("xds:cds") is None
    # Only the counterpart of the invalidated key is deleted.
    assert cache.get("xds:lds") == {"listeners": []}
    invalidate_xds_cache(XDS_CACHE_KEY_LDS)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "collector,key",
    [(collect_clusters, XDS_CACHE_KEY_CDS), (collect_listeners, XDS_CACHE_KEY_LDS), (collect_secrets, XDS_CACHE_KEY_SDS)],
)
def test_non_resource_set_cached_value_is_a_miss(full_service_hierarchy_controller, collector, key):
    # A foreign-format value (e.g. a legacy dict) under the key is rebuilt
    # rather than returned.
    cache.set(key, {"legacy": "dict"})
    rs = collector()
    assert isinstance(rs, ResourceSet)
    assert isinstance(cache.get(key), ResourceSet)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "collector,key",
    [(collect_clusters, XDS_CACHE_KEY_CDS), (collect_listeners, XDS_CACHE_KEY_LDS), (collect_secrets, XDS_CACHE_KEY_SDS)],
)
def test_collectors_cache_with_explicit_timeout(full_service_hierarchy_controller, collector, key):
    # The production cache defaults to no expiry; the TTL must be explicit so
    # a stale rebuild cannot be cached forever.
    with mock.patch.object(xds_resources.cache, "set", wraps=xds_resources.cache.set) as mock_set:
        collector()
    mock_set.assert_called_once()
    assert mock_set.call_args.args[0] == key
    assert mock_set.call_args.kwargs["timeout"] == XDS_CACHE_TIMEOUT == 300


@pytest.mark.django_db
@pytest.mark.parametrize("collector,key", [(collect_clusters, XDS_CACHE_KEY_CDS), (collect_listeners, XDS_CACHE_KEY_LDS)])
def test_filtered_collection_is_not_cached(full_service_hierarchy_controller, collector, key):
    # A filtered subset under the shared unfiltered key would be served to,
    # and pushed to, every Envoy.
    full = collector()
    assert full.resources
    invalidate_xds_cache(key)
    collector(resource_names=["no-such-resource"])
    assert cache.get(key) is None
