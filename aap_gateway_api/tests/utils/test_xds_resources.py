"""Unit tests for the shared xDS resource collectors (no HTTP)."""

from unittest import mock

import pytest
from django.core.cache import cache
from envoy.config.core.v3.config_source_pb2 import ApiVersion
from envoy.config.listener.v3.listener_pb2 import Listener
from envoy.extensions.transport_sockets.tls.v3.tls_pb2 import DownstreamTlsContext

from aap_gateway_api.utils import xds_resources
from aap_gateway_api.utils.xds_resources import (
    XDS_CACHE_KEY_CDS,
    XDS_CACHE_KEY_LDS,
    XDS_CACHE_KEY_LDS_REST,
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
def test_listener_sds_source_is_ads(full_service_hierarchy_controller):
    # Listeners fetch their validation-context secret over the same ADS stream
    # as CDS/LDS rather than polling the REST control plane.
    resource_set = collect_listeners()
    listener = Listener()
    resource_set.resources[0].Unpack(listener)
    tls = DownstreamTlsContext()
    listener.filter_chains[0].transport_socket.typed_config.Unpack(tls)
    sds_config = tls.common_tls_context.validation_context_sds_secret_config.sds_config
    assert sds_config.HasField("ads")
    assert not sds_config.HasField("api_config_source")
    assert sds_config.resource_api_version == ApiVersion.V3


@pytest.mark.django_db
def test_listener_sds_source_is_rest_for_rest_transport(full_service_hierarchy_controller):
    # The REST views serve Envoys whose bootstrap predates ADS; their listeners
    # keep the REST SDS source so nothing depends on the bootstrap having ads_config.
    resource_set = collect_listeners(sds_transport="rest")
    listener = Listener()
    resource_set.resources[0].Unpack(listener)
    tls = DownstreamTlsContext()
    listener.filter_chains[0].transport_socket.typed_config.Unpack(tls)
    sds_config = tls.common_tls_context.validation_context_sds_secret_config.sds_config
    assert sds_config.HasField("api_config_source")
    assert not sds_config.HasField("ads")


@pytest.mark.django_db
def test_rest_listener_variant_has_its_own_cache_key(full_service_hierarchy_controller):
    ads = collect_listeners()
    rest = collect_listeners(sds_transport="rest")
    # Different content (SDS source), so different digests, cached separately.
    assert ads.version != rest.version
    assert cache.get(XDS_CACHE_KEY_LDS).version == ads.version
    assert cache.get(XDS_CACHE_KEY_LDS_REST).version == rest.version

    # Invalidating the LDS key also drops the REST variant.
    invalidate_xds_cache(XDS_CACHE_KEY_LDS)
    assert cache.get(XDS_CACHE_KEY_LDS) is None
    assert cache.get(XDS_CACHE_KEY_LDS_REST) is None


@pytest.mark.django_db
def test_collect_secrets_accepts_resource_names():
    # The ADS servicer calls every collector with resource_names=None; SDS has
    # a single known secret, so the argument has no effect.
    assert collect_secrets(resource_names=None).version == collect_secrets().version


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
