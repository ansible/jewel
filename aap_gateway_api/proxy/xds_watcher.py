"""xDS cache watcher: broadcasts ADS pushes when the collected xDS configuration changes.

Change detection reuses the REST control plane's cache: Django signals
invalidate the CDS/LDS payload cache keys on model changes
(aap_gateway_api/signals/xds_cache.py) and the collectors re-cache non-empty
rebuilds.  This watcher polls those keys and compares each type's digest
against the last version it observed — on every tick, hit or miss, because
the cache is shared by all forked gRPC workers and every gateway node: a
cache miss is seen by at most one worker (the first to rebuild re-caches for
the rest), so the miss itself is not a reliable per-worker change signal.
When the digest differs from the last observed version, the rebuilt
ResourceSet is broadcast to every connected ADS stream via the
StreamRegistry.

Empty configurations are never cached (the no-cache-empty rule shared with
the REST control plane), so with zero routes/ports the watcher re-collects on
every tick.  That is accepted: no broadcast fires (the digest is stable), and
truly-empty deployments are transitional.
"""

import logging
import threading

from django.core.cache import cache
from django.db import close_old_connections

from aap_gateway_api.proxy.ads import CDS_TYPE_URL, LDS_TYPE_URL, StreamRegistry
from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, collect_clusters, collect_listeners

logger = logging.getLogger("aap_gateway_api.proxy.xds_watcher")

# (type_url, cache key, collector) in push order.  CDS is checked first: a
# listener may reference a cluster created in the same change, and Envoy
# rejects listeners whose clusters it does not yet hold.  Collectors are
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
        # type_url -> version (digest) last observed for that type.  The
        # first observation of a type primes this baseline silently.
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
        try:
            # Long-lived thread: its DB connections are never recycled by
            # request signals, so close stale ones here.
            close_old_connections()
            cached = cache.get_many([key for _, key, _ in WATCHED_TYPES])
            for type_url, key, collector in WATCHED_TYPES:
                rs = cached.get(key)
                if rs is None:
                    # Cache miss: invalidated since it was cached, or empty /
                    # never-cached (the no-cache-empty rule re-collects here
                    # every tick; see module docstring).
                    rs = collector(resource_names=None)
                if type_url not in self._last_versions:
                    # First observation (hit or miss): adopt the current
                    # version as the baseline without pushing — streams
                    # receive the current state on subscription
                    # (AggregatedDiscoveryService), so re-pushing it would be
                    # redundant.  This also primes warm-started workers
                    # (cache already populated by another worker or a REST
                    # poll) so their first real change is not swallowed.
                    self._last_versions[type_url] = rs.version
                    continue
                if rs.version != self._last_versions[type_url]:
                    self._last_versions[type_url] = rs.version
                    logger.info("Pushing %s version %s", type_url, rs.version)
                    self.registry.broadcast(("push", (type_url, rs)))
        except Exception:
            # A transient DB/redis error degrades this one tick instead of
            # silently killing the watcher thread.
            logger.exception("xDS watcher tick failed")
