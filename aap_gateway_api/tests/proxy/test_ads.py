"""Unit tests for the gRPC Aggregated Discovery Service (ADS) servicer."""

import logging
import time

import pytest
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryRequest
from google.rpc import status_pb2

from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, AggregatedDiscoveryService, StreamRegistry, _Stream
from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, ResourceSet, invalidate_xds_cache

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


def test_registry_broadcast_puts_event_on_every_stream():
    registry = StreamRegistry()
    streams = [_Stream(FakeContext()) for _ in range(2)]
    for stream in streams:
        registry.add(stream)
    assert registry.streams() == streams

    event = ("push", (CDS_TYPE_URL, ResourceSet(version="v1", resources=[])))
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
    stream.events.put(("push", (LDS_TYPE_URL, ResourceSet(version="pushed-lds", resources=[]))))
    # Give the stream a moment before tearing it down; the queued LDS push is
    # consumed inside next(gen) below, ahead of the inactive-context check.
    time.sleep(0.5)
    ctx.active = False
    # The stream never subscribed to LDS, so the push must not produce a
    # response; if it had, next(gen) would return it here.
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.django_db
def test_push_for_subscribed_type_sends_response(full_service_hierarchy_controller):
    # Complement of test_push_for_unsubscribed_type_sends_nothing.
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    stream = registry.streams()[0]
    pushed = ResourceSet(version=f"pushed-{resp1.version_info}", resources=resp1.resources)
    stream.events.put(("push", (CDS_TYPE_URL, pushed)))
    resp2 = next(gen)

    assert resp2.type_url == CDS_TYPE_URL
    assert resp2.version_info == pushed.version


@pytest.mark.django_db
def test_nonces_unique_across_responses(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    resp1 = next(gen)

    stream = registry.streams()[0]
    pushed = ResourceSet(version=f"pushed-{resp1.version_info}", resources=resp1.resources)
    stream.events.put(("push", (CDS_TYPE_URL, pushed)))
    resp2 = next(gen)

    assert resp2.version_info == pushed.version
    assert resp1.nonce != resp2.nonce
