"""xDS cache watcher: broadcasts ADS pushes when the collected xDS configuration changes.

Change detection reuses the REST control plane's cache: Django signals
invalidate the CDS/LDS payload cache keys on model changes
(aap_gateway_api/signals/xds_cache.py) and the collectors re-cache non-empty
rebuilds.  This watcher polls those keys and compares each type's digest
against the last version it observed — on every tick, hit or miss, because
the cache is shared by all forked gRPC workers and every gateway node: a
cache miss is seen by at most one worker (the first to rebuild re-caches for
the rest), so the miss itself is not a reliable per-worker change signal.
When the digest differs from the last observed version -- including the
first observation of a type -- a ("push", type_url) hint is broadcast to
every connected ADS stream via the StreamRegistry; each stream re-collects
the current state and suppresses versions it already holds.

The watcher does nothing while the worker has no connected ADS streams, so
deployments whose Envoy bootstrap still uses REST xDS pay no polling cost.

Empty configurations are never cached (the no-cache-empty rule shared with
the REST control plane), so with zero routes/ports the watcher re-collects on
every tick while ADS streams are connected.  That is accepted: after the
first observation no broadcast fires (the digest is stable), and truly-empty
deployments are transitional.
"""

import logging
import threading

from django.core.cache import cache
from django.db import close_old_connections

from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, StreamRegistry
from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, as_resource_set, collect_clusters, collect_listeners

logger = logging.getLogger("aap_gateway_api.proxy.xds_watcher")

# (type_url, cache key, collector) in push order.  CDS is checked first: a
# listener may reference a cluster created in the same change, and Envoy
# rejects listeners whose clusters it does not yet hold.  (The ordering holds
# within a tick; the two cache reads are not atomic, so an LDS change can
# occasionally be pushed one tick before its CDS change.)  Collectors are
# always called with resource_names=None (full state) because they cache
# under a shared unfiltered key.
WATCHED_TYPES = (
    (CDS_TYPE_URL, XDS_CACHE_KEY_CDS, collect_clusters),
    (LDS_TYPE_URL, XDS_CACHE_KEY_LDS, collect_listeners),
)


class XDSWatcher(threading.Thread):
    """Polls the xDS payload cache and pushes rebuilds to the connected ADS streams."""

    def __init__(self, registry: StreamRegistry, interval: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.registry = registry
        self.interval = interval
        self._stop_event = threading.Event()
        # type_url -> version (digest) last observed for that type.
        self._last_versions: dict[str, str] = {}

    def run(self) -> None:
        logger.info("xDS cache watcher started (interval=%ss)", self.interval)
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()

    def tick(self) -> None:
        """One poll cycle; also the test entry point."""
        if not self.registry.streams():
            # No connected ADS streams in this worker: nothing to push to.
            # A stream that connects later gets current state on subscription,
            # and any version that differs from the last one observed here is
            # broadcast on the first tick after it connects.
            return
        try:
            # Long-lived thread: its DB connections are never recycled by
            # request signals, so close stale ones here.
            close_old_connections()
            cached = cache.get_many([key for _, key, _ in WATCHED_TYPES])
            for type_url, key, collector in WATCHED_TYPES:
                # A value that is not a ResourceSet (e.g. a foreign format) is
                # treated as a miss.
                rs = as_resource_set(cached.get(key))
                if rs is None:
                    # Cache miss: invalidated since it was cached, or empty /
                    # never-cached (the no-cache-empty rule re-collects here
                    # every tick; see module docstring).
                    rs = collector(resource_names=None)
                # The first observation of a type also broadcasts: a stream
                # that subscribed before this tick may hold an older version
                # if a change landed in between.  Streams that already hold
                # the current version suppress the push
                # (AggregatedDiscoveryService._handle_push).
                if rs.version != self._last_versions.get(type_url):
                    self._last_versions[type_url] = rs.version
                    logger.info("Pushing %s version %s", type_url, rs.version)
                    self.registry.broadcast(("push", type_url))
        except Exception:
            # A transient DB/redis error degrades this one tick instead of
            # silently killing the watcher thread.
            logger.exception("xDS watcher tick failed")
