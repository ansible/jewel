"""Shared xDS resource collectors.

Builds the Envoy CDS/LDS/SDS resources from the database, packs them into
protobuf Any messages, and caches the result.  Both the REST-JSON control
plane views (aap_gateway_api/views/api/envoy/rest_control_plane.py) and the
gRPC ADS servicer consume these collectors so that both transports serve
identical configuration.
"""

import hashlib
import logging
from dataclasses import dataclass

from django.core.cache import cache
from django.db.models import Max, Prefetch
from envoy.config.cluster.v3.cluster_pb2 import Cluster
from envoy.config.listener.v3.listener_pb2 import Listener
from google.protobuf import symbol_database
from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import ParseDict

from aap_gateway_api.models import HTTPPort, Route
from aap_gateway_api.models.ca_certificate import CACertificate
from aap_gateway_api.models.service_cluster import ServiceCluster
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils.xds_configs import SDS_SECRET_CONFIG_NAME

# These modules must be imported so their protobuf message types get registered
# with symbol_database.Default().pool.  Without this, ParseDict() will fail to
# resolve the @type URLs embedded in the xDS resources Envoy expects.
# isort: off
from envoy.extensions.transport_sockets.tls.v3 import tls_pb2  # noqa: F401
from envoy.extensions.filters.http.router.v3 import router_pb2  # noqa: F401
from envoy.extensions.filters.http.lua.v3 import lua_pb2  # noqa: F401
from envoy.extensions.access_loggers.stream.v3 import stream_pb2  # noqa: F401
from envoy.extensions.filters.http.ext_authz.v3 import ext_authz_pb2  # noqa: F401
from envoy.extensions.filters.network.http_connection_manager.v3 import http_connection_manager_pb2  # noqa: F401
from envoy.extensions.retry.host.previous_hosts.v3 import previous_hosts_pb2  # noqa: F401
from envoy.service.secret.v3 import sds_pb2, sds_pb2_grpc  # noqa: F401
from envoy.extensions.transport_sockets.tls.v3.secret_pb2 import Secret

# isort: on

logger = logging.getLogger("aap_gateway_api.utils.xds_resources")

XDS_CACHE_KEY_CDS = "xds:cds"
XDS_CACHE_KEY_LDS = "xds:lds"
XDS_CACHE_KEY_SDS = "xds:sds"


@dataclass
class ResourceSet:
    """A collected xDS resource type: the packed resources and their digest version."""

    version: str  # sha256 hex digest of the packed resources
    resources: list  # list[google.protobuf.any_pb2.Any], packed


def invalidate_xds_cache(*keys: str) -> None:
    """Delete one or more xDS cache keys."""
    cache.delete_many(keys)


def resource_digest(resources) -> str:
    """sha256 hex digest over the concatenation of the serialized resources.

    Resource order comes from the collectors' querysets (their order_by), no
    extra sorting is applied here.
    """
    digest = hashlib.sha256()
    for resource in resources:
        digest.update(resource.SerializeToString(deterministic=True))
    return digest.hexdigest()


def _pack_resources(resource_type, resources) -> list:
    """Pack a list of resource dicts into protobuf Any messages."""
    packed = []
    for resource in resources:
        message = resource_type()
        ParseDict(resource, message, descriptor_pool=symbol_database.Default().pool)

        a = Any()
        a.Pack(message)
        packed.append(a)

    return packed


def _apply_resource_names(qs, name_field, resource_names):
    if resource_names is None:
        return qs
    return qs.filter(**{f"{name_field}__in": resource_names})


def collect_clusters(resource_names: list[str] | None = None) -> ResourceSet:
    """CDS -- an Envoy Cluster definition for every Route."""
    cached = cache.get(XDS_CACHE_KEY_CDS)
    if cached is not None:
        logger.debug("CDS cache hit")
        return cached

    # DISTINCT ON is PostgreSQL-specific; it gives us one row per unique
    # envoy_cluster_name (e.g. one Route per Envoy cluster).
    routes = list(
        _apply_resource_names(Route.objects.order_by("envoy_cluster_name").distinct("envoy_cluster_name"), "envoy_cluster_name", resource_names)
        .select_related('service_cluster')
        .prefetch_related('service_cluster__nodes', 'service_cluster__service_type')
    )

    # Pre-compute the maximum per-route request_timeout_seconds for each
    # ServiceCluster in a single query.  We stash the result as the
    # _max_route_timeout attribute so that
    # ServiceCluster.get_effective_health_check_timeout_seconds() can use
    # it instead of issuing a per-cluster aggregate (N+1).
    cluster_ids = {r.service_cluster_id for r in routes}
    max_timeouts = dict(ServiceCluster.objects.filter(pk__in=cluster_ids).annotate(_max=Max('routes__request_timeout_seconds')).values_list('pk', '_max'))
    for route in routes:
        route.service_cluster._max_route_timeout = max_timeouts.get(route.service_cluster_id)

    clusters = [x.get_xds_cluster_config() for x in routes]
    resources = _pack_resources(Cluster, clusters)
    resource_set = ResourceSet(version=resource_digest(resources), resources=resources)
    # Only cache if we have resources; empty responses during bootstrap should not be cached
    if clusters:
        cache.set(XDS_CACHE_KEY_CDS, resource_set)
    return resource_set


def collect_listeners(resource_names: list[str] | None = None) -> ResourceSet:
    """LDS -- an Envoy Listener for every HTTPPort."""
    cached = cache.get(XDS_CACHE_KEY_LDS)
    if cached is not None:
        logger.debug("LDS cache hit")
        return cached

    # DISTINCT ON is PostgreSQL-specific; it gives us one row per unique
    # envoy_listener_name (e.g. one HTTPPort per Envoy listener).
    ports = _apply_resource_names(
        HTTPPort.objects.order_by("envoy_listener_name").distinct("envoy_listener_name"), "envoy_listener_name", resource_names
    ).prefetch_related(
        Prefetch('routes', queryset=Route.objects.select_related('service_cluster__service_type').order_by('order')),
        'routes__service_cluster__nodes',
    )

    gw_cluster_name = None
    sc = ServiceCluster.objects.filter(service_type__name=DefaultServiceType.GATEWAY.value).first()
    if sc:
        gw_route = Route.objects.filter(service_cluster=sc).first()
        if gw_route:
            gw_cluster_name = gw_route.envoy_cluster_name

    listeners = [x.get_xds_listener_config(gateway_cluster_name=gw_cluster_name) for x in ports]

    resources = _pack_resources(Listener, listeners)
    resource_set = ResourceSet(version=resource_digest(resources), resources=resources)
    # Only cache if we have resources; empty responses during bootstrap should not be cached
    if listeners:
        cache.set(XDS_CACHE_KEY_LDS, resource_set)
    return resource_set


def collect_secrets() -> ResourceSet:
    """SDS -- a single Secret containing all trusted CA certificates."""
    cached = cache.get(XDS_CACHE_KEY_SDS)
    if cached is not None:
        logger.debug("SDS cache hit")
        return cached

    secret_resource = _collect_db_ca_certs()
    resources = _pack_resources(Secret, [secret_resource])
    resource_set = ResourceSet(version=resource_digest(resources), resources=resources)
    cache.set(XDS_CACHE_KEY_SDS, resource_set)
    return resource_set


def _collect_db_ca_certs() -> dict:
    pem_blocks = [(cert.pem_data or "").strip() for cert in CACertificate.objects.all()]
    pem_blocks = [p for p in pem_blocks if p]
    secret = {"name": SDS_SECRET_CONFIG_NAME, "validation_context": {}}
    if pem_blocks:
        secret["validation_context"]["trusted_ca"] = {"inline_string": "\n".join(pem_blocks)}
    return secret
