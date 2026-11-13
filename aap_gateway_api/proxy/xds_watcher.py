"""xDS cache watcher: broadcasts ADS pushes when the xDS payload cache is invalidated.

Change detection reuses the REST control plane's mechanism: Django signals
invalidate the CDS/LDS payload cache keys on model changes
(aap_gateway_api/signals/xds_cache.py).  This watcher polls those keys and,
when one is missing (invalidated) and rebuilds with a digest the watcher has
not already pushed, broadcasts the rebuilt ResourceSet to every connected ADS
stream via the StreamRegistry.

Empty configurations are never cached (the no-cache-empty rule shared with
the REST control plane), so with zero routes/ports the watcher re-collects on
every tick.  That is accepted: no broadcast fires (the digest is stable), and
truly-empty deployments are transitional.
"""

import logging
import threading

from django.core.cache import cache

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
        # type_url -> version of the last ResourceSet this watcher broadcast.
        self._last_versions: dict[str, str] = {}
        # type_urls observed at least once (the first observation is a silent prime).
        self._primed: set[str] = set()

    def run(self) -> None:
        logger.info("xDS cache watcher started (interval=%ss)", self.interval)
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()

    def tick(self) -> None:
        """One poll cycle; also the test entry point."""
        cached = cache.get_many([key for _, key, _ in WATCHED_TYPES])
        for type_url, key, collector in WATCHED_TYPES:
            rs = cached.get(key)
            if rs is not None:
                # Cache hit: the entry has not been invalidated since the
                # collector wrote it, so nothing changed for this type.
                continue
            # Cache miss: either invalidated since it was cached, or empty /
            # never-cached (the no-cache-empty rule re-collects here every
            # tick; see module docstring).
            rs = collector(resource_names=None)
            if type_url not in self._primed:
                # First observation: a silent prime.  Streams receive the
                # current state on subscription (AggregatedDiscoveryService),
                # so re-pushing it would be redundant.  An empty first
                # observation is still recorded as the pushed version so the
                # empty re-collect loop never broadcasts; a non-empty one is
                # not, so the first invalidation after startup pushes the
                # current state once (harmless: the servicer drops versions a
                # stream already holds).
                self._primed.add(type_url)
                if not rs.resources:
                    self._last_versions[type_url] = rs.version
                continue
            if rs.version != self._last_versions.get(type_url):
                self._last_versions[type_url] = rs.version
                logger.info("Pushing %s version %s", type_url, rs.version)
                self.registry.broadcast(("push", (type_url, rs)))
