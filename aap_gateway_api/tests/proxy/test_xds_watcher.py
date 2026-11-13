"""Unit tests for the xDS cache watcher (ADS pushes on cache invalidation)."""

import queue

import pytest

from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, StreamRegistry, _Stream
from aap_gateway_api.proxy.xds_watcher import XDSWatcher
from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, invalidate_xds_cache


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


@pytest.fixture(autouse=True)
def _clear_xds_cache():
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    yield
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


@pytest.mark.django_db
def test_tick_pushes_on_invalidation(full_service_hierarchy_controller):
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # primes cache and last_versions
    assert stream.events.empty() or drain(stream.events) == []  # nothing pushed without a change
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    watcher.tick()
    kind, (type_url, rs) = stream.events.get(timeout=1)
    assert kind == "push" and type_url == CDS_TYPE_URL and rs.version != ""
    # LDS was not invalidated, so it must not have been pushed either.
    assert stream.events.empty()


@pytest.mark.django_db
def test_tick_no_push_when_digest_unchanged(full_service_hierarchy_controller):
    # Prime, invalidate, tick (pushes once), invalidate again without any model change, tick
    # → queue must stay empty (spurious invalidation, identical rebuild)
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # prime
    assert drain(stream.events) == []

    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    watcher.tick()
    pushed = drain(stream.events)
    assert len(pushed) == 1  # pushed once, CDS only
    kind, (type_url, rs) = pushed[0]
    assert kind == "push" and type_url == CDS_TYPE_URL

    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
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
    # Invalidate both keys; one tick must queue CDS push before LDS push
    registry = StreamRegistry()
    stream = make_fake_stream(registry)
    watcher = XDSWatcher(registry)
    watcher.tick()  # prime
    assert drain(stream.events) == []

    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS)
    watcher.tick()
    pushed = drain(stream.events)
    assert [kind for kind, _ in pushed] == ["push", "push"]
    assert [payload[0] for _, payload in pushed] == [CDS_TYPE_URL, LDS_TYPE_URL]
