"""Unit tests for the gRPC Aggregated Discovery Service (ADS) servicer."""

import logging
import time
from unittest import mock

import pytest
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryRequest
from google.rpc import status_pb2

import aap_gateway_api.proxy.ads as ads_module
from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, AggregatedDiscoveryService, StreamRegistry, _Stream
from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, collect_clusters, invalidate_xds_cache

UNKNOWN_TYPE_URL = "type.googleapis.com/envoy.config.route.v3.RouteConfiguration"


class FakeContext:
    """Minimal grpc ServicerContext stand-in with a settable active flag."""

    def __init__(self):
        self.active = True

    def is_active(self):
        return self.active


@pytest.fixture(autouse=True)
def _clear_xds_cache():
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    yield
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


@pytest.fixture(autouse=True)
def _mock_close_old_connections():
    # The servicer recycles its pooled thread's DB connections via
    # close_old_connections() before collecting; driven synchronously from
    # the test thread it would instead close pytest-django's
    # transaction-wrapped test connection (same treatment as
    # tests/proxy/test_xds_watcher.py).
    with mock.patch("aap_gateway_api.proxy.ads.close_old_connections") as close:
        yield close


def change_cds_config(route):
    """Make a real CDS-affecting model change and invalidate the CDS cache key
    (on_commit invalidation does not fire inside pytest-django's transaction)."""
    route.is_service_https = not route.is_service_https
    route.save()
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)


def assert_stream_sends_nothing_more(gen, ctx):
    """Let queued events drain, end the stream, and assert nothing was sent."""
    # The queued events are consumed inside next(gen), ahead of the
    # inactive-context check; if any had produced a response, next(gen)
    # would return it instead of raising.
    time.sleep(0.5)
    ctx.active = False
    with pytest.raises(StopIteration):
        next(gen)


def test_registry_broadcast_puts_event_on_every_stream():
    registry = StreamRegistry()
    streams = [_Stream(FakeContext()) for _ in range(2)]
    for stream in streams:
        registry.add(stream)
    assert registry.streams() == streams

    event = ("push", CDS_TYPE_URL)
    registry.broadcast(event)
    assert streams[0].events.get_nowait() is event
    assert streams[1].events.get_nowait() is event

    registry.remove(streams[0])
    assert registry.streams() == [streams[1]]


@pytest.mark.django_db
def test_initial_subscription_returns_current_state(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    req = DiscoveryRequest(type_url=CDS_TYPE_URL)  # no version_info = initial request
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([req]), ctx)
    resp = next(gen)
    assert resp.type_url == CDS_TYPE_URL
    assert resp.version_info != ""
    assert resp.nonce != ""
    assert len(resp.resources) > 0
    ctx.active = False


@pytest.mark.django_db
def test_ack_with_current_version_sends_nothing(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    stream = registry.streams()[0]
    ack = DiscoveryRequest(type_url=CDS_TYPE_URL, version_info=resp1.version_info, response_nonce=resp1.nonce)
    stream.events.put(("request", ack))
    # Give the stream a moment before tearing it down; the queued ACK is
    # consumed inside next(gen) below, ahead of the inactive-context check.
    time.sleep(0.5)
    ctx.active = False
    # If the ACK had produced a response, next(gen) would return it here.
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.django_db
def test_nack_is_logged_and_sends_nothing(full_service_hierarchy_controller, caplog):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    stream = registry.streams()[0]
    # Envoy rejects resp1 and holds no ACKed version yet, so version_info is
    # empty -- a mishandled NACK would fall through and re-send a response.
    nack = DiscoveryRequest(
        type_url=CDS_TYPE_URL,
        response_nonce=resp1.nonce,
        error_detail=status_pb2.Status(code=13, message="invalid cluster config"),
    )
    with caplog.at_level(logging.WARNING, logger="aap_gateway_api.proxy.ads"):
        stream.events.put(("request", nack))
        # Give the stream a moment before tearing it down; the queued NACK is
        # consumed inside next(gen) below, ahead of the inactive-context check.
        time.sleep(0.5)
        ctx.active = False
        # A NACK is logged and dropped; if it had produced a response,
        # next(gen) would return it here.
        with pytest.raises(StopIteration):
            next(gen)
    assert "invalid cluster config" in caplog.text


def test_unknown_type_url_logged_and_ignored(caplog):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=UNKNOWN_TYPE_URL)]), ctx)
    with caplog.at_level(logging.WARNING, logger="aap_gateway_api.proxy.ads"):
        ctx.active = False
        with pytest.raises(StopIteration):
            # The unknown request is consumed and ignored (no response); the
            # inactive context then ends the stream.
            next(gen)
    assert UNKNOWN_TYPE_URL in caplog.text
    assert registry.streams() == []


@pytest.mark.django_db
def test_stream_removed_from_registry_on_context_inactive(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    next(gen)
    assert len(registry.streams()) == 1
    ctx.active = False
    with pytest.raises(StopIteration):
        next(gen)  # generator loop sees inactive context, cleans up, returns
    assert len(registry.streams()) == 0


@pytest.mark.django_db
def test_push_for_unsubscribed_type_sends_nothing(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    # This stream subscribes to CDS only.
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    next(gen)

    stream = registry.streams()[0]
    stream.events.put(("push", LDS_TYPE_URL))
    # Give the stream a moment before tearing it down; the queued LDS push is
    # consumed inside next(gen) below, ahead of the inactive-context check.
    time.sleep(0.5)
    ctx.active = False
    # The stream never subscribed to LDS, so the push must not produce a
    # response; if it had, next(gen) would return it here.
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.django_db
def test_push_for_subscribed_type_sends_current_state(full_service_hierarchy_controller):
    # Complement of test_push_for_unsubscribed_type_sends_nothing: a push is a
    # "type changed" hint; the servicer re-collects and sends current state.
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    change_cds_config(full_service_hierarchy_controller.route)
    stream = registry.streams()[0]
    stream.events.put(("push", CDS_TYPE_URL))
    resp2 = next(gen)

    assert resp2.type_url == CDS_TYPE_URL
    assert resp2.version_info != resp1.version_info
    assert resp2.version_info == collect_clusters().version
    assert len(resp2.resources) > 0


@pytest.mark.django_db
def test_push_for_version_already_held_sends_nothing(full_service_hierarchy_controller):
    # A push whose re-collected state matches what the stream last sent is
    # suppressed (the watcher's first-observation hint, a late hint after a
    # request already sent the newer state, duplicate hints).
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    next(gen)

    stream = registry.streams()[0]
    stream.events.put(("push", CDS_TYPE_URL))
    stream.events.put(("push", CDS_TYPE_URL))
    assert_stream_sends_nothing_more(gen, ctx)


@pytest.mark.django_db
def test_stale_push_after_newer_request_does_not_roll_back(full_service_hierarchy_controller):
    # A request collected V2 and sent it; a push hint queued for an earlier
    # change is processed afterwards.  It must not send anything older than V2
    # (and, as V2 is current, sends nothing at all).
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    change_cds_config(full_service_hierarchy_controller.route)
    stream = registry.streams()[0]
    # Envoy re-requests (e.g. after reconnecting its subscription) and gets V2...
    stream.events.put(("request", DiscoveryRequest(type_url=CDS_TYPE_URL, version_info=resp1.version_info + "-other")))
    resp2 = next(gen)
    assert resp2.version_info == collect_clusters().version != resp1.version_info
    # ...then the watcher's hint for the same change arrives late.
    stream.events.put(("push", CDS_TYPE_URL))
    assert_stream_sends_nothing_more(gen, ctx)


@pytest.mark.django_db
def test_request_recycles_db_connections_before_collecting(full_service_hierarchy_controller, _mock_close_old_connections):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    next(gen)
    _mock_close_old_connections.assert_called()
    ctx.active = False


def test_collector_failure_is_logged_and_ends_stream(caplog, monkeypatch):
    def boom(resource_names=None):
        raise RuntimeError("simulated collector failure")

    monkeypatch.setitem(ads_module.COLLECTORS, CDS_TYPE_URL, boom)
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    with caplog.at_level(logging.WARNING, logger="aap_gateway_api.proxy.ads"):
        with pytest.raises(RuntimeError, match="simulated collector failure"):
            next(gen)
    assert any(r.levelno == logging.WARNING and r.exc_info for r in caplog.records)
    assert registry.streams() == []


@pytest.mark.django_db
def test_nonces_unique_across_responses(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    change_cds_config(full_service_hierarchy_controller.route)
    stream = registry.streams()[0]
    stream.events.put(("push", CDS_TYPE_URL))
    resp2 = next(gen)

    assert resp2.version_info != resp1.version_info
    assert resp1.nonce != resp2.nonce
