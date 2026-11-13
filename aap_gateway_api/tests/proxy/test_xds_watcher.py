"""Unit tests for the xDS cache watcher (ADS pushes on config change)."""

import logging
import queue
from unittest import mock

import pytest
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryRequest

import aap_gateway_api.proxy.xds_watcher as xds_watcher_module
from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, AggregatedDiscoveryService, StreamRegistry, _Stream
from aap_gateway_api.proxy.xds_watcher import XDSWatcher
from aap_gateway_api.utils.xds_resources import (
    XDS_CACHE_KEY_CDS,
    XDS_CACHE_KEY_LDS,
    XDS_CACHE_KEY_SDS,
    collect_clusters,
    collect_listeners,
    invalidate_xds_cache,
)


class FakeContext:
    """Minimal grpc ServicerContext stand-in with a settable active flag."""

    def __init__(self):
        self.active = True

    def is_active(self):
        return self.active


def make_fake_stream(registry):
    """A bare _Stream registered in the registry, as a connected Envoy would be."""
    stream = _Stream(FakeContext())
    registry.add(stream)
    return stream


def drain(events):
    """Empty an event queue into a list."""
    drained = []
    while True:
        try:
            drained.append(events.get_nowait())
        except queue.Empty:
            return drained


def pushed_types(events):
    """The (kind, type_url) pairs of the events drained from a stream queue."""
    return drain(events)


def prime(watcher, stream):
    """Run the watcher's first tick, which hints every type once (the current
    state, which a subscribed stream suppresses if it already holds it), and
    discard those hints."""
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL), ("push", LDS_TYPE_URL)]


def change_cds_config(route):
    """Make a real CDS-affecting model change (is_service_https changes the
    cluster's transport socket) and invalidate the CDS cache key."""
    route.is_service_https = not route.is_service_https
    route.save()
    # transaction.on_commit receivers (used by the invalidation signals) do
    # not fire inside pytest-django's wrapped transaction, so invalidate
    # explicitly to simulate the signal's on_commit effect.
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)


@pytest.fixture(autouse=True)
def _clear_xds_cache():
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    yield
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


@pytest.fixture(autouse=True)
def _mock_close_old_connections():
    # tick() recycles the watcher thread's DB connections via
    # close_old_connections(); called synchronously from the test thread it
    # would instead close pytest-django's transaction-wrapped test connection
    # (same treatment as tests/proxy/test_proxy.py and
    # tests/views/api/v1/ping/test_ping.py).
    with mock.patch("aap_gateway_api.proxy.xds_watcher.close_old_connections"), mock.patch("aap_gateway_api.proxy.ads.close_old_connections"):
        yield


def test_tick_is_noop_without_streams():
    # No connected ADS streams in the worker: no cache reads, no DB rebuilds.
    watcher = XDSWatcher(StreamRegistry())
    with mock.patch.object(xds_watcher_module.cache, "get_many") as get_many, mock.patch.object(xds_watcher_module, "close_old_connections") as close:
        watcher.tick()
    get_many.assert_not_called()
    close.assert_not_called()
    assert watcher._last_versions == {}


@pytest.mark.django_db
def test_first_tick_hints_current_state(full_service_hierarchy_controller):
    # The first observation of each type broadcasts once (no silent prime),
    # recording the current state; streams that already hold it suppress the
    # push (AggregatedDiscoveryService._handle_push, see test_ads.py).
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL), ("push", LDS_TYPE_URL)]
    assert watcher._last_versions[CDS_TYPE_URL] == collect_clusters().version
    assert watcher._last_versions[LDS_TYPE_URL] == collect_listeners().version

    watcher.tick()  # unchanged: no further pushes
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_pushes_on_model_change(full_service_hierarchy_controller):
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    kind, type_url = stream.events.get(timeout=1)
    assert kind == "push" and type_url == CDS_TYPE_URL
    assert watcher._last_versions[CDS_TYPE_URL] == collect_clusters().version
    # and no LDS push followed a CDS-only change
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_no_push_when_digest_unchanged(full_service_hierarchy_controller):
    # Prime, model change + invalidate, tick (pushes once), invalidate again
    # WITHOUT any model change, tick → queue must stay empty
    # (identical rebuild produces the same digest — the digest, not the
    # cache miss, is the change signal)
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL)]  # pushed once, CDS only

    invalidate_xds_cache(XDS_CACHE_KEY_CDS)  # spurious: no model change this time
    watcher.tick()
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_empty_db_broadcasts_only_first_observation():
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)  # collects (possibly empty, uncached) state, hints once
    watcher.tick()  # unchanged — must not broadcast again
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_pushes_cds_before_lds(full_service_hierarchy_controller):
    # Make CDS- and LDS-affecting model changes, invalidate both keys; one
    # tick must queue CDS push before LDS push
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)

    route = full_service_hierarchy_controller.route
    route.is_service_https = not route.is_service_https  # CDS-affecting
    route.gateway_path = f"{route.gateway_path}x"  # LDS-affecting
    route.save()
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL), ("push", LDS_TYPE_URL)]


@pytest.mark.django_db
def test_tick_warm_cache_first_tick_then_change(full_service_hierarchy_controller):
    # Pre-warm the cache, then start a NEW watcher (the warm-start case for
    # workers started after the first): its first tick observes the cached
    # version and hints it once; a subsequent model change + invalidate must
    # push.
    collect_clusters()
    collect_listeners()
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL)]


@pytest.mark.django_db
def test_tick_treats_foreign_cached_value_as_miss(full_service_hierarchy_controller):
    # A value that is not a ResourceSet under the key (foreign format) is a
    # miss: the watcher re-collects instead of raising.
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    xds_watcher_module.cache.set(XDS_CACHE_KEY_CDS, {"clusters": []})
    prime(watcher, stream)
    assert watcher._last_versions[CDS_TYPE_URL] == collect_clusters().version


@pytest.mark.django_db
def test_stream_subscribed_before_first_tick_gets_intervening_change(full_service_hierarchy_controller):
    # Startup race: a stream subscribes before the watcher's first tick and a
    # change lands in between.  The first tick must deliver the change; the
    # unchanged type is suppressed by the servicer.
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL), DiscoveryRequest(type_url=LDS_TYPE_URL)]), ctx)
    cds1 = next(gen)
    lds1 = next(gen)
    assert (cds1.type_url, lds1.type_url) == (CDS_TYPE_URL, LDS_TYPE_URL)

    change_cds_config(full_service_hierarchy_controller.route)
    watcher = XDSWatcher(registry)
    watcher.tick()  # first observation: hints CDS and LDS

    cds2 = next(gen)
    assert cds2.type_url == CDS_TYPE_URL
    assert cds2.version_info != cds1.version_info
    assert cds2.version_info == collect_clusters().version
    # The LDS hint is suppressed (stream already holds the current LDS);
    # nothing else is sent before the stream ends.
    ctx.active = False
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.django_db
def test_two_watchers_share_one_cache(full_service_hierarchy_controller):
    # Two watchers with separate registries on one cache (the 5-forked-worker
    # topology): a model change + invalidate → BOTH watchers push to their
    # own streams (the first to rebuild re-caches; the other must see the
    # new version on its cache hit and still push)
    registry_a = StreamRegistry()
    registry_b = StreamRegistry()
    stream_a = make_fake_stream(registry_a)
    stream_b = make_fake_stream(registry_b)
    watcher_a = XDSWatcher(registry_a)
    watcher_b = XDSWatcher(registry_b)
    prime(watcher_a, stream_a)
    prime(watcher_b, stream_b)

    change_cds_config(full_service_hierarchy_controller.route)
    watcher_a.tick()  # sees the miss, rebuilds, re-caches, pushes
    watcher_b.tick()  # sees only the re-cached hit — must still push
    assert pushed_types(stream_a.events) == [("push", CDS_TYPE_URL)]
    assert pushed_types(stream_b.events) == [("push", CDS_TYPE_URL)]


@pytest.mark.django_db
def test_tick_survives_collector_error(full_service_hierarchy_controller, caplog, monkeypatch):
    # A transient collector failure (DB/redis hiccup) must degrade a single
    # tick instead of killing the watcher thread: tick() does not raise, the
    # failure is logged, and the next good tick still pushes.
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    prime(watcher, stream)

    change_cds_config(full_service_hierarchy_controller.route)

    def boom(resource_names=None):
        raise RuntimeError("simulated collector failure")

    monkeypatch.setattr(xds_watcher_module, "WATCHED_TYPES", ((CDS_TYPE_URL, XDS_CACHE_KEY_CDS, boom), (LDS_TYPE_URL, XDS_CACHE_KEY_LDS, collect_listeners)))
    with caplog.at_level(logging.ERROR, logger="aap_gateway_api.proxy.xds_watcher"):
        watcher.tick()  # must not raise
    assert "simulated collector failure" in caplog.text
    assert pushed_types(stream.events) == []

    monkeypatch.undo()
    watcher.tick()  # the next good tick still pushes
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL)]
