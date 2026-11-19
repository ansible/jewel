import logging
import socket

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext as _

from aap_gateway_api.common.envoy import EXT_AUTH_FILTER, EXT_AUTH_PER_ROUTE
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils.xds_configs import (
    external_auth_filter,
    http_router_filter,
    network_manager_filter,
    path_rewrite_filter,
    redirect_route,
    transport_socket,
)

logger = logging.getLogger("aap_gateway_api.models.http_port")


def get_xds_url_prefix():
    """Return the xDS REST route namespace (for example ``/v3/``).

    Envoy fetches its xDS configuration from the control plane directly (gRPC
    ADS, or the REST cluster in its bootstrap), never through its own
    listeners, so no listener should forward requests in this namespace to the
    gateway API, where the catch-all gateway service route would otherwise
    proxy them. This namespace is reserved: ``AdditionalRoute`` rejects paths
    under it because the deny route below is evaluated first, which would
    silently shadow such a route. Derive the prefix from the URL conf so new
    discovery routes or a version bump cannot be exposed by omission.
    """
    return "/" + reverse("lds").lstrip("/").split("/", 1)[0] + "/"


def get_xds_deny_prefixes(configured_routes):
    """Return listener prefixes that can reach the gateway's xDS namespace.

    The xDS namespace is always reachable at the site root through the gateway
    catch-all route. Envoy matches on the downstream path before applying
    ``prefix_rewrite``, so any route that proxies to the gateway service
    cluster also exposes the namespace under its own ``gateway_path`` base.
    """
    xds_prefix = get_xds_url_prefix()
    prefixes = {xds_prefix}
    for route in configured_routes:
        if route.service_cluster.service_type.name != DefaultServiceType.GATEWAY.value:
            continue
        service_path = route.service_path.rstrip("/") + "/"
        base = route.gateway_path.rstrip("/")
        if service_path.startswith(xds_prefix):
            # The route already rewrites into the namespace, so every request
            # through it lands in xDS territory.
            prefixes.add(f"{base}/")
            continue
        # A route only exposes xDS when its rewrite lands inside the namespace.
        if not xds_prefix.startswith(service_path):
            continue
        remainder = xds_prefix[len(service_path) :]
        prefixes.add(f"{base}/{remainder}" if remainder else f"{base}/")
    return sorted(prefixes)


def _drf_not_found():
    """Return the status, body, and content type DRF uses for a 404."""
    from rest_framework.exceptions import NotFound
    from rest_framework.renderers import JSONRenderer
    from rest_framework.views import exception_handler

    response = exception_handler(NotFound(), {})
    renderer = JSONRenderer()
    return response.status_code, renderer.render(response.data), renderer.media_type


class HTTPPort(UniqueNamedCommonModel, AuditableModel):
    """
    Represents a port that Envoy will listen for HTTP traffic on.
    """

    router_basename = 'http_port'

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("is_api_port",),
                name="unique_api_port",
                condition=models.Q(is_api_port=True),
            )
        ]

    number = models.IntegerField(
        blank=False, unique=True, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("The port number to listen on.")
    )

    use_https = models.BooleanField(default=True, help_text=_("Secure this port with HTTPS."))

    # only one can be true
    is_api_port = models.BooleanField(
        default=False, help_text=_("If true, this port will be used to serve the Ansible service APIs. Only one port can be the API port.")
    )

    envoy_listener_name = models.CharField(max_length=255, help_text=_("The envoy configuration listener name for this port."))

    def __str__(self):
        protocol = "https" if self.use_https else "http"
        out = f"{self.number}/{protocol}"
        if self.is_api_port:
            out += " (API port)"
        return out

    def save(self, *args, **kwargs):
        self.envoy_listener_name = f"port-{self.number}"

        return super().save(*args, **kwargs)

    def get_xds_listener_config(self, **kwargs):
        """
        Return the Envoy listener configuration for this port.

        API ports also redirect bare ``/api`` and service API paths to their
        trailing-slash forms without invoking external authorization.

        Args:
            **kwargs: Keyword arguments forwarded to each route's XDS
                configuration builder.
        """
        http_filters = [
            path_rewrite_filter(),
            external_auth_filter(),
            http_router_filter(),
        ]

        routes = []
        configured_routes = sorted(self.routes.all(), key=lambda r: r.order)
        # Allow envoy to respond to /up itself without auth
        up_route = {
            "match": {"prefix": "/up"},
            "direct_response": {"status": 200, "body": {"inline_string": "UP"}},
            "typed_per_filter_config": {EXT_AUTH_FILTER: {"@type": EXT_AUTH_PER_ROUTE, "disabled": True}},
        }
        routes.append(up_route)
        # Envoy talks to the control plane directly, so no listener should
        # forward xDS discovery requests to the gateway API. Serve the same
        # 404 response DRF returns for the gateway API.
        status, body, content_type = _drf_not_found()
        for prefix in get_xds_deny_prefixes(configured_routes):
            routes.append(
                {
                    "match": {"prefix": prefix},
                    "direct_response": {"status": status, "body": {"inline_string": body.decode()}},
                    "response_headers_to_add": [
                        {"header": {"key": "content-type", "value": content_type}},
                    ],
                    "typed_per_filter_config": {EXT_AUTH_FILTER: {"@type": EXT_AUTH_PER_ROUTE, "disabled": True}},
                }
            )
        if self.is_api_port:
            redirects = {"/api": "/api/"}
            redirects.update(
                (svc_route.gateway_path.rstrip("/"), svc_route.gateway_path)
                for svc_route in configured_routes
                if svc_route.gateway_path.startswith("/api/") and svc_route.gateway_path.endswith("/")
            )
            routes.extend(redirect_route(path, target) for path, target in redirects.items())
        for route in configured_routes:
            routes.extend(route.get_xds_route_config(**kwargs))

        cfg = {
            "name": self.envoy_listener_name,
            "address": {"socket_address": {"address": "::", "port_value": self.number, "ipv4_compat": True}},
            "filter_chains": [
                {
                    "filters": [
                        network_manager_filter(http_filters=http_filters, routes=routes),
                    ]
                }
            ],
            "per_connection_buffer_limit_bytes": settings.ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES,
        }

        # If IPv6 is not available, fall back to IPv4
        if not is_ipv6_enabled():
            cfg['address']['socket_address'] = {"address": "0.0.0.0", "port_value": self.number}

        if self.use_https:
            cfg["filter_chains"][0]["transport_socket"] = transport_socket()

        return cfg

    def get_listener_name(self):
        return f"port-{self.number}"


def is_ipv6_enabled():
    """Check if IPv6 is available."""
    try:
        v6sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        v6sock.close()
        logger.debug("IPv6 is available, binding to ::")
        return True
    except (OSError, socket.error, AttributeError):
        logger.debug("IPv6 is not available, binding to 0.0.0.0")
        return False
