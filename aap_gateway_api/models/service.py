from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext as _

from aap_gateway_api.utils.xds_configs import external_auth_filter, http_router_filter, network_manager_filter, path_rewrite_filter, transport_socket

API_PREFIX = "/api/"


class HTTPPort(UniqueNamedCommonModel):
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
        blank=False, unique=True, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("Port number to listen on.")
    )

    use_https = models.BooleanField(default=True, help_text=_("Secure this port with HTTPS."))

    # only one can be true
    is_api_port = models.BooleanField(
        default=False, help_text=_("If true, this port will be used to serve the AAP service APIs. Only one port can be the API port.")
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
                        network_manager_filter(http_filters=http_filters, routes=[r.get_xds_route_config() for r in self.routes.all().order_by('order')]),
                    ]
                }
            ],
        }

        if self.use_https:
            cfg["filter_chains"][0]["transport_socket"] = transport_socket()

        return cfg

    def get_listener_name(self):
        return f"port-{self.number}"


class ServiceCluster(UniqueNamedCommonModel):
    """
    Represents an AAP Service which can be comprised of multiple load balanced nodes.
    """

    router_basename = 'service_cluster'

    class ServiceType(models.TextChoices):
        HUB = "hub", "hub"
        CONTROLLER = "controller", "controller"
        EDA = "eda", "eda"
        GATEWAY = "gateway", "gateway"

    service_type = models.CharField(
        # We can remove this if/when we add support for multiple services of each type.
        unique=True,
        max_length=11,
        choices=ServiceType.choices,
        help_text=_(
            "The type of service for this cluster.",
        ),
    )

    service_id = models.UUIDField(unique=True, help_text="The unique service ID, provided by the service.", null=True, editable=False)

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        response['service_type'] = self.get_service_type_display()
        return response

    def __str__(self):
        return self.get_service_type_display()


class ServiceNode(UniqueNamedCommonModel):
    """
    Individual node in a service cluster.
    """

    router_basename = 'service_node'

    class Meta:
        models.UniqueConstraint("address", name="one_address_per_gateway")

    service_cluster = models.ForeignKey(
        ServiceCluster, related_name='nodes', on_delete=models.CASCADE, help_text=_("AAP Service cluster that this node belongs to.")
    )
    address = models.CharField(max_length=255, help_text=_("Network address to route traffic for this service to."))


class Route(UniqueNamedCommonModel):
    """
    Represents one route to a specific AAP Service cluster. Each route must be
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
        unique_together = ('http_port', 'gateway_path')

    http_port = models.ForeignKey(
        HTTPPort, related_name="routes", blank=False, on_delete=models.CASCADE, help_text=_("Port on the AAP gateway to listen to traffic on.")
    )
    service_cluster = models.ForeignKey(ServiceCluster, related_name="routes", on_delete=models.CASCADE, help_text=_("AAP Service to route traffic to."))

    service_port = models.IntegerField(
        blank=False, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("Port on the service cluster to route traffic to.")
    )
    is_service_https = models.BooleanField(help_text=_("Set this to true if the service cluster requires HTTPS."))

    service_path = models.CharField(max_length=255, blank=False, help_text=_("URL path on the AAP Service cluster to route traffic to."))
    gateway_path = models.CharField(max_length=255, blank=False, help_text=_("Path on the AAP gateway to listen to traffic on."))

    description = models.CharField(max_length=255, blank=True, null=True)

    # Some routes, such as EDA webhooks, have their own authentication and my not need
    # gateway authentication tokens.
    enable_gateway_auth = models.BooleanField(default=True, help_text=_("If false, the AAP gateway will not insert a gateway token into the proxied request."))

    # Our setup here is a little bit weird. In the envoy model, ports are configured on the cluster object
    # but in this case we're configuring them on the route since all of the ports should be the same for every
    # ServiceNode. Because of that if multiple routes are configured for the same service on the same port,
    # they should point to the same cluster (which is a combination of ServiceCluster and Route). To avoid
    # creating a duplicate cluster with the same address/port combo, we're going to save a name for the
    # cluster in the db to identify the ServiceCluster/port combo.
    envoy_cluster_name = models.CharField(max_length=255, null=False)

    # The order of the routes
    order = models.IntegerField(
        default=50,
        validators=[MaxValueValidator(100), MinValueValidator(0)],
        help_text=_("The order to apply the routes in lower numbers are first. Items with the same value have no guaranteed order"),
    )

    def save(self, *args, **kwargs):
        self.envoy_cluster_name = f"cluster-{self.service_cluster.pk}-{self.service_port}"

        return super().save(*args, **kwargs)

    def get_xds_cluster_config(self):
        endpoints = []
        for node in self.service_cluster.nodes.all():
            endpoints.append({"endpoint": {"address": {"socket_address": {"address": node.address, "port_value": self.service_port}}}})

        cfg = {
            "name": self.envoy_cluster_name,
            # LOGICAL_DNS can not have multiple endpoints defined in it because they assume that DNS for a single node will respond with multiple hosts
            # STRICT_DNS should give us the characteristics we want where if a node is removed from a cluster
            #            the connections we be drained and traffic will stop being routed there.
            "type": "STRICT_DNS",
            "lb_policy": "LEAST_REQUEST",
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

    router_basename = 'service'

    api_slug = models.SlugField(max_length=20)

    class Meta:
        models.UniqueConstraint("service_cluster", name="one_service_api_per_service")

    def save(self, *args, **kwargs):
        self.http_port = HTTPPort.objects.get(is_api_port=True)
        # gateway_path is part of unique key + read only, which means it's repeated in
        # GatewayConfiguration collection::AAPService
        # Note: when this code is changed, AAPService has to be changed too
        if self.api_slug == 'gateway':
            self.gateway_path = '/'
        else:
            self.gateway_path = API_PREFIX + self.api_slug + "/"

        return super().save(*args, **kwargs)


class AdditionalRoute(Route):
    """
    Use this for configuring additional routes outside of the routes that are served from API_PREFIX.

    This model contains extra validation to ensure that custom routes don't conflict with the services
    that run on the api port.
    """

    router_basename = 'route'

    def clean(self):
        if self.http_port.is_api_port and self.gateway_path.startswith(API_PREFIX):
            raise ValidationError({'gateway_path': _("Custom routes on the API port cannot start with '{API_PREFIX}'").format(API_PREFIX=API_PREFIX)})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
