import logging
import time
import uuid as _uuid_mod
from typing import Optional

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils import resources_client

logger = logging.getLogger('aap.gateway.utils.service_id_sync')

# Per-issuer cooldown for the lazy auth fallback — prevents serial DB+HTTP calls on
# repeated unknown tokens (e.g. a mis-configured or attacker-supplied JWT).
_lazy_populate_cooldown: dict[str, float] = {}
_LAZY_POPULATE_COOLDOWN_SECONDS = 60
_LAZY_POPULATE_MAX_COOLDOWN_ENTRIES = 1000

# Cap on how many null-id clusters are probed per unknown-issuer auth request.
# Bounds the number of outbound HTTP calls on the first request from each issuer.
_MAX_CLUSTERS_TO_PROBE = 5

# Service types eligible for lazy service_id population on the auth hot path.
# Restricting to known DefaultServiceType values (excluding GATEWAY) prevents the
# lazy path from probing custom or unknown service types during token validation.
_LAZY_SYNCABLE_TYPES = [e.value for e in DefaultServiceType if e != DefaultServiceType.GATEWAY]


def _check_and_set_cooldown(issuer: str) -> bool:
    """Returns True if issuer is on cooldown (caller should skip), False if ok to proceed.

    Prunes expired entries when the dict grows past the cap to prevent unbounded growth.

    Args:
        issuer: The JWT iss claim string used as the cooldown key.

    Returns:
        True if a recent attempt was made for this issuer, False otherwise.
    """
    now = time.monotonic()
    if len(_lazy_populate_cooldown) > _LAZY_POPULATE_MAX_COOLDOWN_ENTRIES:
        cutoff = now - _LAZY_POPULATE_COOLDOWN_SECONDS
        expired = [k for k, t in _lazy_populate_cooldown.items() if t < cutoff]
        for k in expired:
            del _lazy_populate_cooldown[k]

    if now - _lazy_populate_cooldown.get(issuer, 0) < _LAZY_POPULATE_COOLDOWN_SECONDS:
        return True

    _lazy_populate_cooldown[issuer] = now
    return False


def _fetch_service_id_for_route(service_api: ServiceAPIRoute, user=None) -> Optional[str]:
    """Calls the service metadata endpoint and returns a validated service_id string.

    Args:
        service_api: The ServiceAPIRoute whose upstream to query.
        user: Optional user for JWT signing. Falls back to the first superuser.

    Returns:
        A valid UUID string for the service_id, or None if the fetch failed,
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
            _uuid_mod.UUID(raw_id)
        except ValueError:
            logger.warning("Invalid service_id value '%s' from %s metadata", raw_id, service_api.api_slug)
            return None

        return raw_id
    except Exception:
        logger.exception("Failed to fetch metadata for cluster %s", service_api.service_cluster.name)
        return None


def populate_missing_service_ids(user=None, force: bool = False) -> tuple[list[str], list[str]]:
    """Fetches and persists service_id for clusters that need one.

    Skips clusters of type GATEWAY (they self-assign in ServiceCluster.save()).
    Skips clusters that have no ServiceAPIRoute.
    Uses a conditional UPDATE (when not forced) to be safe against concurrent calls.

    Args:
        user: Optional user for JWT signing on metadata requests.
        force: When True, re-fetches and overwrites service_id for all non-gateway clusters,
            including those that already have one. Use after a service re-deployment or
            disaster recovery to ensure stored IDs match what each service reports.

    Returns:
        A tuple of (populated_names, failed_names) — lists of cluster names.
    """
    populated: list[str] = []
    failed: list[str] = []

    qs = ServiceCluster.objects.exclude(service_type__name=DefaultServiceType.GATEWAY.value).select_related('service_type')

    clusters = list(qs if force else qs.filter(service_id__isnull=True))
    if not clusters:
        return populated, failed

    # Single query for all ServiceAPIRoutes to avoid N+1.
    api_routes_by_cluster = {r.service_cluster_id: r for r in ServiceAPIRoute.objects.filter(service_cluster_id__in=[c.pk for c in clusters])}

    for cluster in clusters:
        service_api = api_routes_by_cluster.get(cluster.pk)
        if service_api is None:
            logger.warning("No ServiceAPIRoute for cluster %s — skipping", cluster.name)
            failed.append(cluster.name)
            continue

        fetched_id = _fetch_service_id_for_route(service_api, user=user)
        if not fetched_id:
            failed.append(cluster.name)
            continue

        # Without --force: conditional update guards against concurrent writes.
        # With --force: unconditionally overwrite whatever is stored.
        filter_kw = {"pk": cluster.pk} if force else {"pk": cluster.pk, "service_id__isnull": True}
        rows = ServiceCluster.objects.filter(**filter_kw).update(service_id=fetched_id)
        if rows or ServiceCluster.objects.filter(pk=cluster.pk, service_id=fetched_id).exists():
            logger.info("Populated service_id %s for cluster %s", fetched_id, cluster.name)
            populated.append(cluster.name)
        else:
            logger.warning("Could not confirm service_id write for cluster %s", cluster.name)
            failed.append(cluster.name)

    return populated, failed


def try_populate_service_id(unverified_service_id: str) -> Optional[ServiceCluster]:
    """Lazy fallback: checks null-id clusters for one whose metadata matches the given UUID.

    Intended for use inside token validation when a ServiceCluster.DoesNotExist is raised.
    A per-issuer cooldown prevents this from triggering serial DB+HTTP calls on every
    request when a service is persistently unreachable or the issuer is unknown.
    At most _MAX_CLUSTERS_TO_PROBE clusters are probed to bound outbound HTTP calls.
    All exceptions from HTTP calls are caught and logged — this never raises.

    Args:
        unverified_service_id: The UUID string from the JWT's iss claim.

    Returns:
        The populated ServiceCluster if a matching cluster was found, None otherwise.
    """
    if _check_and_set_cooldown(unverified_service_id):
        logger.debug("Lazy service_id populate skipped for %s (on cooldown)", unverified_service_id)
        return None

    # Single query: null-id clusters of known service types only, capped to limit HTTP calls.
    # Restricting to _LAZY_SYNCABLE_TYPES means the lazy auth path never probes custom
    # or unknown service types during token validation.
    api_routes = ServiceAPIRoute.objects.filter(
        service_cluster__service_id__isnull=True,
        service_cluster__service_type__name__in=_LAZY_SYNCABLE_TYPES,
    ).select_related('service_cluster', 'service_cluster__service_type')[:_MAX_CLUSTERS_TO_PROBE]

    for service_api in api_routes:
        cluster = service_api.service_cluster

        fetched_id = _fetch_service_id_for_route(service_api)
        if not fetched_id or fetched_id != unverified_service_id:
            continue

        rows = ServiceCluster.objects.filter(pk=cluster.pk, service_id__isnull=True).update(service_id=fetched_id)
        if rows or ServiceCluster.objects.filter(pk=cluster.pk, service_id=fetched_id).exists():
            cluster.service_id = fetched_id  # sync in-memory object to avoid extra DB round-trip
            logger.warning(
                "Lazily populated service_id %s for cluster %s — run sync_service_ids to avoid this on future requests",
                fetched_id,
                cluster.name,
            )
            return cluster

    return None
