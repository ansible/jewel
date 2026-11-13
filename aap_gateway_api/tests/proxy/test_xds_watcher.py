"""Unit tests for the xDS cache watcher (ADS pushes on config change)."""

import logging
import queue
from unittest import mock

import pytest

import aap_gateway_api.proxy.xds_watcher as xds_watcher_module
from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, StreamRegistry, _Stream
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
    """Minimal grpc ServicerContext stand-in; the watcher never touches it."""

    def is_active(self):
        return True


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
    return [(kind, payload[0]) for kind, payload in drain(events)]


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
    with mock.patch("aap_gateway_api.proxy.xds_watcher.close_old_connections"):
        yield


@pytest.mark.django_db
def test_tick_pushes_on_model_change(full_service_hierarchy_controller):
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # primes baseline (first observation, silently)
    assert stream.events.empty()  # nothing pushed without a change

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    kind, (type_url, rs) = stream.events.get(timeout=1)
    assert kind == "push" and type_url == CDS_TYPE_URL and rs.version != ""
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
    watcher.tick()  # prime
    assert pushed_types(stream.events) == []

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL)]  # pushed once, CDS only

    invalidate_xds_cache(XDS_CACHE_KEY_CDS)  # spurious: no model change this time
    watcher.tick()
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_empty_db_no_broadcast():
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # collects empty (uncached) — must not broadcast
    watcher.tick()  # still empty — must not broadcast
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_pushes_cds_before_lds(full_service_hierarchy_controller):
    # Make CDS- and LDS-affecting model changes, invalidate both keys; one
    # tick must queue CDS push before LDS push
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # prime
    assert pushed_types(stream.events) == []

    route = full_service_hierarchy_controller.route
    route.is_service_https = not route.is_service_https  # CDS-affecting
    route.gateway_path = f"{route.gateway_path}x"  # LDS-affecting
    route.save()
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS)
    watcher.tick()
    pushed = drain(stream.events)
    assert [kind for kind, _ in pushed] == ["push", "push"]
    assert [payload[0] for _, payload in pushed] == [CDS_TYPE_URL, LDS_TYPE_URL]


@pytest.mark.django_db
def test_tick_warm_cache_prime_is_silent(full_service_hierarchy_controller):
    # Pre-warm the cache (run another watcher's tick, or call the collector
    # directly), then start a NEW watcher: its first tick observes the cached
    # version and must not push; a subsequent model change + invalidate must
    # push (the warm-start case for workers started after the first)
    collect_clusters()
    collect_listeners()
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()
    assert pushed_types(stream.events) == []

    change_cds_config(full_service_hierarchy_controller.route)
    watcher.tick()
    assert pushed_types(stream.events) == [("push", CDS_TYPE_URL)]


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
    watcher_a.tick()
    watcher_b.tick()
    assert pushed_types(stream_a.events) == []
    assert pushed_types(stream_b.events) == []

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
    watcher.tick()  # prime
    assert pushed_types(stream.events) == []

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
