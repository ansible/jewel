from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from aap_gateway_api.models.common import CommonModel, NamedCommonModel
from aap_gateway_api.utils.xds_configs import external_auth_filter, http_router_filter, network_manager_filter, path_rewrite_filter, transport_socket

API_PREFIX = "/api/"


class HTTPPort(CommonModel):
    """
    Represents a port that Envoy will listen for HTTP traffic on.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("is_api_port",),
                name="unique_api_port",
                condition=models.Q(is_api_port=True),
            )
        ]

    number = models.IntegerField(blank=False, unique=True, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text="Port number to listen on.")

    use_https = models.BooleanField(default=True, help_text="Secure this port with HTTPS.")

    # only one can be true
    is_api_port = models.BooleanField(
        default=False, help_text="If true, this port will be used to serve the Ansible service APIs. Only one port can be the API port."
    )

    envoy_listener_name = models.CharField(max_length=255)

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

        cfg = {
            "name": self.envoy_listener_name,
            "address": {"socket_address": {"address": "0.0.0.0", "port_value": self.number}},
            "filter_chains": [
                {
                    "filters": [
                        network_manager_filter(http_filters=http_filters, routes=[r.get_xds_route_config() for r in self.routes.all()]),
                    ]
                }
            ],
        }

        if self.use_https:
            cfg["filter_chains"][0]["transport_socket"] = transport_socket()

        return cfg

    def get_listener_name(self):
        return f"port-{self.number}"


class ServiceCluster(CommonModel):
    """
    Represents an Ansible service which can be comprised of multiple load balanced nodes.
    """

    class ServiceType(models.TextChoices):
        HUB = "h", "hub"
        CONTROLLER = "c", "controller"
        EDA = "e", "eda"
        GATEWAY = "g", "gateway"

    service_type = models.CharField(
        # We can remove this if/when we add support for multiple services of each type.
        unique=True,
        max_length=1,
        choices=ServiceType.choices,
        help_text="The type of service for this cluster.",
    )

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        response['service_type'] = self.get_service_type_display()
        return response

    def __str__(self):
        return self.get_service_type_display()


class ServiceNode(CommonModel):
    """
    Individual node in a service cluster.
    """

    class Meta:
        unique_together = ('service', 'address')

    service = models.ForeignKey(ServiceCluster, related_name='nodes', on_delete=models.CASCADE, help_text="Ansible service cluster that this node belongs to.")
    address = models.CharField(max_length=255, help_text="Network address to route traffic for this service to.")


class Route(NamedCommonModel):
    """
    Represents one route to a specific Ansible service cluster. Each route must be
    configured to listen on a pre configured HTTP port, and multiple routes can
    be configured for each port.

    Example:
                                                                 node 1: 192.168.0.20
                                                               /
    /api/hub/ -> :443 (api port) ---- > Hub ServiceCluster --< - node 2: 192.168.0.21
                                    /                          \
    /v2/ -> :443 (api port) -------                              node 3: 192.168.0.22


                                                                 node 1: 192.168.0.20
                                                               /
    /api/eda/ -> :443 (api port) ---- > EDA ServiceCluster --< - node 2: 192.168.0.21
                                    /                          \
    / -> :9021 (webhook port) -----                              node 3: 192.168.0.22
    """

    class Meta:
        unique_together = ('port', 'gateway_path')

    port = models.ForeignKey(
        HTTPPort, related_name="routes", blank=False, on_delete=models.CASCADE, help_text="Port on the gateway to listen to traffic on."
    )
    service_cluster = models.ForeignKey(ServiceCluster, related_name="routes", on_delete=models.CASCADE, help_text="Ansible service to route traffic to.")

    service_port = models.IntegerField(
        blank=False, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text="Port on the service cluster to route traffic to."
    )
    is_service_https = models.BooleanField(help_text="Set this to true if the service cluster requires HTTPS.")

    service_path = models.CharField(max_length=255, blank=False, help_text="URL path on the Ansible service cluster to route traffic to.")
    gateway_path = models.CharField(max_length=255, blank=False, help_text="Path on the gateway to listen to traffic on.")

    description = models.CharField(max_length=255, blank=True, null=True)

    # Some routes, such as EDA webhooks, have their own authentication and my not need
    # gateway authentication tokens.
    enable_gateway_auth = models.BooleanField(default=True, help_text="If false, the gateway will not insert a Gateway token into the proxied request.")

    # Our setup here is a little bit weird. In the envoy model, ports are configured on the cluster object
    # but in this case we're configuring them on the route since all of the ports should be the same for every
    # ServiceNode. Because of that if multiple routes are configured for the same service on the same port,
    # they should point to the same cluster (which is a combination of ServiceCluster and Route). To avoid
    # creating a duplicate cluster with the same address/port combo, we're going to save a name for the
    # cluster in the db to identify the ServiceCluster/port combo.
    envoy_cluster_name = models.CharField(max_length=255, null=False)

    def save(self, *args, **kwargs):
        self.envoy_cluster_name = f"cluster-{self.service_cluster.pk}-{self.service_port}"

        return super().save(*args, **kwargs)

    def get_xds_cluster_config(self):
        endpoints = []
        for node in self.service_cluster.nodes.all():
            endpoints.append({"endpoint": {"address": {"socket_address": {"address": node.address, "port_value": self.service_port}}}})

        cfg = {
            "name": self.envoy_cluster_name,
            "type": "LOGICAL_DNS",
            "dns_lookup_family": "ALL",
            "load_assignment": {"cluster_name": self.envoy_cluster_name, "endpoints": [{"lb_endpoints": endpoints}]},
        }

        if self.is_service_https:
            cfg["transport_socket"] = {
                "name": "envoy.transport_sockets.tls",
                "typed_config": {"@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext"},
            }

        return cfg

    def get_xds_route_config(self):
        cfg = {
            "match": {"prefix": self.gateway_path},
            "route": {"prefix_rewrite": self.service_path, "cluster": self.envoy_cluster_name},
            "metadata": {},
            "typed_per_filter_config": {},
        }

        if self.service_path != self.gateway_path:
            cfg["metadata"]["filter_metadata"] = {"envoy.filters.http.lua": {"prefix": self.gateway_path, "prefix_rewrite": self.service_path}}

            cfg["typed_per_filter_config"]["envoy.filters.http.lua"] = {
                "@type": "type.googleapis.com/envoy.extensions.filters.http.lua.v3.LuaPerRoute",
                "name": "rewrite.lua",
            }

        if not self.enable_gateway_auth:
            cfg["typed_per_filter_config"]["envoy.filters.http.ext_authz"] = {
                "@type": "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
                "disabled": True,
            }

        return cfg


class ServiceAPIRoute(Route):
    """
    This is a special instance of a route that is intended to be served from /api/ on the
    API port. It has a few requirements that normal Routes don't have.

    - It must be served on the HTTPPort marked as is_api_port=True
    - The gateway_path must be set to /api/{slug}/

    By subclassing the Route model, API routes can be queried along with all of the other
    routes that are configured on Envoy. This makes it much easier to generate the envoy
    xDS configurations.
    """

    api_slug = models.SlugField(max_length=20)

    class Meta:
        models.UniqueConstraint("service_cluster", name="one_service_api_per_service")

    def save(self, *args, **kwargs):
        self.port = HTTPPort.objects.get(is_api_port=True)
        self.gateway_path = API_PREFIX + self.api_slug + "/"

        return super().save(*args, **kwargs)


class AdditionalRoute(Route):
    """
    Use this for configuring additional routes outside of the routes that are served from API_PREFIX.

    This model contains extra validation to ensure that custom routes don't conflict with the services
    that run on the api port.
    """

    def clean(self):
        if self.port.is_api_port and self.gateway_path.startswith(API_PREFIX):
            raise ValidationError({'gateway_path': f"Custom routes on the API port cannot start with '{API_PREFIX}'"})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
