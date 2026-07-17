import logging
import threading
import time
import uuid as _uuid_mod
from typing import Optional

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils import resources_client

logger = logging.getLogger('aap.gateway.utils.service_id_sync')

# Per-issuer cooldown for the auth fallback — prevents serial DB+HTTP calls on
# repeated unknown tokens (e.g. a mis-configured or attacker-supplied JWT).
_populate_cooldown: dict[str, float] = {}
_populate_cooldown_lock = threading.Lock()
_POPULATE_COOLDOWN_SECONDS = 60
_POPULATE_MAX_COOLDOWN_ENTRIES = 1000

# Cap on how many null-id clusters are probed per unknown-issuer auth request.
# Bounds the number of outbound HTTP calls on the first request from each issuer.
_MAX_CLUSTERS_TO_PROBE = 5

# Service types eligible for automatic service_id population on the auth path.
# Restricting to known DefaultServiceType values (excluding GATEWAY) prevents the
# fallback from probing custom or unknown service types during token validation.
_SYNCABLE_TYPES = [e.value for e in DefaultServiceType if e != DefaultServiceType.GATEWAY]


def _check_and_set_cooldown(issuer: str) -> bool:
    """Returns True if issuer is on cooldown (caller should skip), False if ok to proceed.

    Prunes expired entries when the dict exceeds the cap. If the dict is still full after
    pruning (all entries are fresh), the new issuer is blocked without being added —
    preventing unbounded growth under a flood of unique attacker-supplied tokens.

    Note: _populate_cooldown is per-process. In a multi-worker deployment each worker
    maintains its own dict; the DoS bound is per-worker (_MAX_CLUSTERS_TO_PROBE × N workers).

    Args:
        issuer: The JWT iss claim string used as the cooldown key.

    Returns:
        True if a recent attempt was made for this issuer (or the dict is full), False otherwise.
    """
    now = time.monotonic()
    with _populate_cooldown_lock:
        if len(_populate_cooldown) >= _POPULATE_MAX_COOLDOWN_ENTRIES:
            cutoff = now - _POPULATE_COOLDOWN_SECONDS
            expired = [k for k, t in _populate_cooldown.items() if t < cutoff]
            for k in expired:
                del _populate_cooldown[k]
            if len(_populate_cooldown) >= _POPULATE_MAX_COOLDOWN_ENTRIES:
                # Still full after pruning — all entries are fresh. Refuse without adding
                # so the dict cannot grow without bound under a flood of unique tokens.
                return True

        if now - _populate_cooldown.get(issuer, 0) < _POPULATE_COOLDOWN_SECONDS:
            return True

        _populate_cooldown[issuer] = now
        return False


def _fetch_service_id_for_route(service_api: ServiceAPIRoute, user=None) -> Optional[str]:
    """Calls the service metadata endpoint and returns a validated service_id string.

    Args:
        service_api: The ServiceAPIRoute whose upstream to query.
        user: Optional user for JWT signing. Falls back to the first superuser.

    Returns:
        A valid UUID string in canonical lowercase form, or None if the fetch failed,
        returned no id, or returned an invalid value.
    """
    try:
        client = resources_client.GWResourceAPIClient(service_api, user=user)
        response = client.get_service_metadata()
        if response.status_code != 200:
            logger.warning("Metadata fetch for %s returned %s", service_api.api_slug, response.status_code)
            return None

        raw_id = str(response.json().get("service_id") or "").strip()
        try:
            # Parse and re-serialize to normalize to lowercase canonical form so that the
            # comparison with the JWT iss claim never mismatches due to casing or formatting.
            return str(_uuid_mod.UUID(raw_id))
        except ValueError:
            logger.warning("Invalid service_id value '%s' from %s metadata", raw_id, service_api.api_slug)
            return None
    except Exception:
        logger.exception("Failed to fetch metadata for cluster %s", service_api.service_cluster.name)
        return None


def populate_service_id(unverified_service_id: str) -> Optional[ServiceCluster]:
    """Finds and populates service_id for a cluster whose metadata matches the given UUID.

    Called during token validation when a ServiceCluster.DoesNotExist is raised — a service
    registered after migrate_service_data ran (e.g. added in a later upgrade) will have
    service_id=null on its ServiceCluster. This function probes null-id clusters of known
    service types to find a match, writes the id, and returns the cluster so the caller
    can continue authentication without an extra DB round-trip.

    A per-issuer cooldown prevents serial DB+HTTP calls on repeated requests from an
    unknown or attacker-supplied issuer. At most _MAX_CLUSTERS_TO_PROBE clusters are
    probed per request to bound outbound HTTP calls. All DB and HTTP operations are wrapped
    in a broad except so that a transient DB error returns None rather than propagating a
    500 through the gRPC auth handler.

    Args:
        unverified_service_id: The UUID string from the JWT's iss claim.

    Returns:
        The populated ServiceCluster if a matching cluster was found, None otherwise.
    """
    # Normalize to canonical lowercase so the cooldown key and comparison are consistent
    # regardless of how the JWT iss claim was formatted (uppercase, braced, etc.).
    # An invalid (non-UUID) issuer can never match any cluster — return None immediately.
    try:
        canonical_id = str(_uuid_mod.UUID(unverified_service_id))
    except ValueError:
        logger.debug("JWT iss claim is not a valid UUID: %s", unverified_service_id)
        return None

    if _check_and_set_cooldown(canonical_id):
        logger.debug("Service_id populate skipped for %s (on cooldown)", canonical_id)
        return None

    try:
        # Single query: null-id clusters of known service types only, capped to limit HTTP calls.
        # Restricting to _SYNCABLE_TYPES means the fallback never probes custom or unknown
        # service types during token validation.
        api_routes = (
            ServiceAPIRoute.objects.filter(
                service_cluster__service_id__isnull=True,
                service_cluster__service_type__name__in=_SYNCABLE_TYPES,
            )
            .order_by('service_cluster__pk')
            .select_related('service_cluster', 'service_cluster__service_type')[:_MAX_CLUSTERS_TO_PROBE]
        )

        for service_api in api_routes:
            cluster = service_api.service_cluster

            fetched_id = _fetch_service_id_for_route(service_api)
            if not fetched_id or fetched_id != canonical_id:
                continue

            rows = ServiceCluster.objects.filter(pk=cluster.pk, service_id__isnull=True).update(service_id=fetched_id)
            if rows or ServiceCluster.objects.filter(pk=cluster.pk, service_id=fetched_id).exists():
                cluster.service_id = fetched_id  # sync in-memory object to avoid extra DB round-trip
                logger.info("Populated service_id %s for cluster %s", fetched_id, cluster.name)
                return cluster

    except Exception:
        logger.exception("Unexpected error during service_id populate for %s", unverified_service_id)

    return None
