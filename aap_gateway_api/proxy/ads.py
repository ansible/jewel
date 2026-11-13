"""gRPC Aggregated Discovery Service (ADS) for Envoy.

Envoy opens one bidirectional StreamAggregatedResources RPC and multiplexes
all xDS resource types (CDS, LDS, ...) over it.  This module implements the
server side of that stream: each connected stream is registered in a
StreamRegistry (which the cache-invalidation watcher broadcasts pushes to),
new subscriptions are answered with the current state from the shared xDS
collectors, NACKs are logged and dropped, and pushes are sent only for
resource types the stream subscribed to and only for versions it does not
already hold.
"""

import logging
import queue
import threading
import uuid

from envoy.service.discovery.v3 import ads_pb2_grpc
from envoy.service.discovery.v3.discovery_pb2 import DiscoveryRequest, DiscoveryResponse

from aap_gateway_api.utils.xds_resources import ResourceSet, collect_clusters, collect_listeners

CDS_TYPE_URL = "type.googleapis.com/envoy.config.cluster.v3.Cluster"
LDS_TYPE_URL = "type.googleapis.com/envoy.config.listener.v3.Listener"

# The xDS resource types this servicer serves, mapped to their collectors.
COLLECTORS = {
    CDS_TYPE_URL: collect_clusters,
    LDS_TYPE_URL: collect_listeners,
}

logger = logging.getLogger("aap_gateway_api.proxy.ads")


class _Stream:
    """State for one Envoy ADS stream: its context, event queue, and per-type versions."""

    def __init__(self, context) -> None:
        self.context = context
        # ("request", DiscoveryRequest) and ("push", (type_url, ResourceSet)) tuples.
        self.events: queue.Queue = queue.Queue()
        self.subscribed: set[str] = set()
        self.last_versions: dict[str, str] = {}
        self.lock = threading.Lock()

    def read_requests(self, request_iterator) -> None:
        """Drain the gRPC request iterator onto the event queue.

        Runs on a daemon thread; iterator exhaustion (Envoy closed the RPC)
        or a gRPC error ends it silently.
        """
        while True:
            try:
                request = next(request_iterator)
            except StopIteration:
                return
            except Exception:  # gRPC raises when the client goes away.
                return
            self.events.put(("request", request))


class StreamRegistry:
    """The currently connected ADS streams."""

    def __init__(self) -> None:
        self._streams: list[_Stream] = []
        self._lock = threading.Lock()

    def add(self, stream: _Stream) -> None:
        with self._lock:
            self._streams.append(stream)

    def remove(self, stream: _Stream) -> None:
        with self._lock:
            try:
                self._streams.remove(stream)
            except ValueError:
                pass

    def streams(self) -> list[_Stream]:
        with self._lock:
            return list(self._streams)

    def broadcast(self, event: tuple) -> None:
        """Put an event on every registered stream's queue."""
        for stream in self.streams():
            stream.events.put(event)


class AggregatedDiscoveryService(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
    """Serves CDS/LDS to Envoy over a single aggregated gRPC stream."""

    def __init__(self, registry: StreamRegistry | None = None) -> None:
        self.registry = registry if registry is not None else StreamRegistry()

    def StreamAggregatedResources(self, request_iterator, context):
        stream = _Stream(context)
        self.registry.add(stream)
        reader = threading.Thread(target=stream.read_requests, args=(request_iterator,), daemon=True)
        reader.start()
        try:
            while True:
                try:
                    event = stream.events.get(timeout=0.5)
                except queue.Empty:
                    # End the stream only once the client is gone AND pending
                    # events are drained, so a cancellation racing queued
                    # events cannot drop them.
                    if not context.is_active():
                        break
                    continue
                kind, payload = event
                if kind == "request":
                    response = self._handle_request(stream, payload)
                else:
                    response = self._handle_push(stream, payload)
                if response is not None:
                    yield response
        finally:
            self.registry.remove(stream)

    def _handle_request(self, stream: _Stream, request: DiscoveryRequest) -> DiscoveryResponse | None:
        type_url = request.type_url
        if type_url not in COLLECTORS:
            logger.warning("Ignoring DiscoveryRequest for unsupported type_url %r", type_url)
            return None
        stream.subscribed.add(type_url)
        if request.error_detail.code != 0:
            # NACK: Envoy rejected the configuration we last sent.  Log and drop --
            # re-sending the same config would loop NACKs at network speed against
            # a real Envoy client.  Nothing is lost: the next push with a new
            # version still goes out because _handle_push compares against the
            # last-sent version.
            logger.warning("Envoy NACK for %s: %s", type_url, request.error_detail.message)
            return None
        if request.version_info and request.version_info == stream.last_versions.get(type_url):
            # ACK of the version we last sent; nothing to send.
            return None
        # Always collect the full resource set and ignore request.resource_names:
        # the collectors cache under a shared unfiltered key, so a filtered
        # collection would poison that cache with a subset.  Envoy applies
        # full-state responses correctly regardless of what it subscribed to.
        resource_set = COLLECTORS[type_url](resource_names=None)
        return self._build_response(stream, type_url, resource_set)

    def _handle_push(self, stream: _Stream, payload: tuple) -> DiscoveryResponse | None:
        type_url, resource_set = payload
        if type_url not in stream.subscribed:
            # The stream never subscribed to this resource type; an unsolicited
            # response is something Envoy does not expect.
            return None
        if resource_set.version == stream.last_versions.get(type_url):
            return None
        return self._build_response(stream, type_url, resource_set)

    def _build_response(self, stream: _Stream, type_url: str, resource_set: ResourceSet) -> DiscoveryResponse:
        with stream.lock:
            stream.last_versions[type_url] = resource_set.version
        return DiscoveryResponse(
            version_info=resource_set.version,
            nonce=uuid.uuid4().hex,
            resources=resource_set.resources,
            type_url=type_url,
        )
