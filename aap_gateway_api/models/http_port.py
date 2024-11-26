from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext as _

from aap_gateway_api.utils.xds_configs import external_auth_filter, http_router_filter, network_manager_filter, path_rewrite_filter, transport_socket


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
        default=False, help_text=_("If true, this port will be used to serve the AAP service APIs. Only one port can be the API port.")
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

    def get_xds_listener_config(self):
        """
        Returns the envoy listener configuration for this port.
        """
        http_filters = [
            path_rewrite_filter(),
            external_auth_filter(),
            http_router_filter(),
        ]

        routes = []
        for route in self.routes.all().order_by('order'):
            routes.extend(route.get_xds_route_config())

        cfg = {
            "name": self.envoy_listener_name,
            "address": {"socket_address": {"address": "0.0.0.0", "port_value": self.number}},
            "filter_chains": [
                {
                    "filters": [
                        network_manager_filter(http_filters=http_filters, routes=routes),
                    ]
                }
            ],
            "per_connection_buffer_limit_bytes": settings.ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES,
        }

        if self.use_https:
            cfg["filter_chains"][0]["transport_socket"] = transport_socket()

        return cfg

    def get_listener_name(self):
        return f"port-{self.number}"
