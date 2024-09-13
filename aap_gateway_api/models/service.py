from datetime import datetime

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.resource_registry.models import service_id
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext as _

from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.utils.resources_client import ServiceTypeChoices
from aap_gateway_api.utils.xds_configs import external_auth_filter, http_router_filter, network_manager_filter, path_rewrite_filter, transport_socket

API_PREFIX = "/api/"

# This is a list of API endpoints across supported services that Envoy will ping to determine if a node is healthy.
# This is also used by aap_gateway_api.views.api.v1.status
# TODO: This should move somewhere, but not sure where yet.
SERVICE_PING_PAGES = {"gateway": "/api/gateway/v1/ping/", "hub": "/pulp/api/v3/status/", "controller": "/api/v2/ping/", "eda": "/api/eda/v1/status/"}


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
        blank=False, unique=True, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("Port number to listen on.")
    )

    use_https = models.BooleanField(default=True, help_text=_("Secure this port with HTTPS."))

    # only one can be true
    is_api_port = models.BooleanField(
        default=False, help_text=_("If true, this port will be used to serve the Ansible service APIs. Only one port can be the API port.")
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


class ServiceCluster(UniqueNamedCommonModel, AuditableModel):
    """
    Represents an Ansible service which can be comprised of multiple load balanced nodes.
    """

    router_basename = 'service_cluster'

    ServiceType = ServiceTypeChoices

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

    outlier_detection_enabled = models.BooleanField(
        default=True,
        help_text=_("If true, outlier detection will be used to determine if a node is unhealthy and should be ejected from the cluster."),
    )

    outlier_detection_consecutive_5xx = models.PositiveIntegerField(
        default=5,
        help_text=_("Number of consecutive 5xx responses to consider a node unhealthy."),
    )

    outlier_detection_interval_seconds = models.PositiveIntegerField(
        default=10,
        help_text=_("The time interval between ejection analysis sweeps."),
    )

    outlier_detection_base_ejection_time_seconds = models.PositiveIntegerField(
        default=30,
        help_text=_("The base time a node will be ejected for."),
    )

    outlier_detection_max_ejection_percent = models.PositiveIntegerField(
        default=33,
        help_text=_("The maximum percent of nodes that can be ejected from the cluster."),
    )

    health_checks_enabled = models.BooleanField(
        default=True,
        help_text=_("If true, health checks will be used to determine if a node is healthy."),
    )

    health_check_timeout_seconds = models.PositiveIntegerField(
        default=5,
        help_text=_("The time to wait for a health check to complete."),
    )

    health_check_interval_seconds = models.PositiveIntegerField(
        default=10,
        help_text=_("The time between health check requests."),
    )

    health_check_unhealthy_threshold = models.PositiveIntegerField(
        default=3,
        help_text=_("The number of consecutive failed health checks before a node is considered unhealthy."),
    )

    health_check_healthy_threshold = models.PositiveIntegerField(
        default=3,
        help_text=_("The number of consecutive successful health checks before a node is considered healthy."),
    )

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        response['service_type'] = self.get_service_type_display()
        return response

    def __str__(self):
        return self.get_service_type_display()

    def save(self, *args, **kwargs):
        # Set the service id for the gateway.
        if self.service_type == ServiceCluster.ServiceType.GATEWAY and not self.service_id:
            self.service_id = service_id()
        return super().save(*args, **kwargs)

    def generate_key(self, name="", algorithm="HS256", secret_length=64, mark_previous_inactive=True):
        from aap_gateway_api.models import ServiceKey

        if not name:
            name = f"{self.name} - {datetime.now()}"

        if mark_previous_inactive:
            for key in self.service_keys.filter(is_active=True):
                key.is_active = False
                key.save()

        new_key = ServiceKey.objects.create(
            name=name,
            algorithm=algorithm,
            service_cluster=self,
            secret_length=secret_length,
        )

        # Refresh the obj from the DB so that the secret gets decrypted.
        new_key.refresh_from_db()

        return new_key

    def delete_inactive_keys(self):
        self.service_keys.filter(is_active=False).delete()


class ServiceNode(UniqueNamedCommonModel, AuditableModel):
    """
    Individual node in a service cluster.
    """

    router_basename = 'service_node'

    class Meta:
        models.UniqueConstraint("address", name="one_address_per_gateway")

    service_cluster = models.ForeignKey(
        ServiceCluster, related_name='nodes', on_delete=models.CASCADE, help_text=_("Ansible service cluster that this node belongs to.")
    )
    address = models.CharField(max_length=255, help_text=_("Network address to route traffic for this service to."))
    tags = models.CharField(
        max_length=255,
        blank=True,
        null=False,
        default="",
        help_text=_("Comma-separated. Used to assign roles to a node, to be selective about which routes point to it."),
    )

    def tags_list(self):
        return [tag.strip() for tag in self.tags.split(",")] if self.tags else []


class Route(UniqueNamedCommonModel, AuditableModel):
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
        unique_together = ('http_port', 'gateway_path')

    http_port = models.ForeignKey(
        HTTPPort, related_name="routes", blank=False, on_delete=models.CASCADE, help_text=_("Port on the gateway to listen to traffic on.")
    )
    service_cluster = models.ForeignKey(ServiceCluster, related_name="routes", on_delete=models.CASCADE, help_text=_("Ansible service to route traffic to."))

    service_port = models.IntegerField(
        blank=False, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("Port on the service cluster to route traffic to.")
    )
    is_service_https = models.BooleanField(help_text=_("Set this to true if the service cluster requires HTTPS."))

    service_path = models.CharField(max_length=255, blank=False, help_text=_("URL path on the Ansible service cluster to route traffic to."))
    gateway_path = models.CharField(max_length=255, blank=False, help_text=_("Path on the gateway to listen to traffic on."))

    description = models.CharField(max_length=255, blank=True, null=True)

    # Some routes, such as EDA webhooks, have their own authentication and my not need
    # gateway authentication tokens.
    enable_gateway_auth = models.BooleanField(default=True, help_text=_("If false, the gateway will not insert a gateway token into the proxied request."))

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

    node_tags = models.CharField(
        max_length=255,
        blank=True,
        null=False,
        default="",
        help_text=_(
            "Comma-separated. Allows for being selective about which nodes in the service cluster receive traffic from this route. "
            "Leave blank to select all nodes."
        ),
    )

    def node_tags_list(self):
        return [tag.strip() for tag in self.node_tags.split(",")] if self.node_tags else []

    def save(self, *args, **kwargs):
        nodes = self.node_tags_list()

        # Sort the list of nodes so that if the same set of tags are provided in a different order, it will result
        # in the same cluster being created for envoy.
        nodes.sort()
        if len(nodes) == 0:
            nodes = "*"
        else:
            nodes = ",".join(nodes)

        # The same route can result in the same envoy cluster if the set of nodes and service port are the same.
        self.envoy_cluster_name = f"cluster-{self.service_cluster.pk}-{self.service_port}-nodes:{nodes}"

        return super().save(*args, **kwargs)

    def get_xds_cluster_config(self):
        endpoints = []
        for node in self.service_cluster.nodes.all():
            if self.node_tags and not any(tag in node.tags_list() for tag in self.node_tags_list()):
                # Skip nodes that don't have the required tags, if tags are specified.
                continue

            endpoint = {
                "endpoint": {
                    "address": {
                        "socket_address": {
                            "address": node.address,
                            "port_value": self.service_port,
                        },
                    },
                },
            }
            if self.service_cluster.health_checks_enabled:
                endpoint["endpoint"]["health_check_config"] = {
                    "hostname": node.address,
                    "port_value": self.service_port,
                }
            endpoints.append(endpoint)

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

        if self.service_cluster.outlier_detection_enabled:
            cfg["outlier_detection"] = {
                "consecutive_5xx": self.service_cluster.outlier_detection_consecutive_5xx,
                "interval": f"{self.service_cluster.outlier_detection_interval_seconds}s",
                "base_ejection_time": f"{self.service_cluster.outlier_detection_base_ejection_time_seconds}s",
                "max_ejection_percent": self.service_cluster.outlier_detection_max_ejection_percent,
            }

        if self.service_cluster.health_checks_enabled:
            cfg["health_checks"] = [
                {
                    "timeout": f"{self.service_cluster.health_check_timeout_seconds}s",
                    "interval": f"{self.service_cluster.health_check_interval_seconds}s",
                    "unhealthy_threshold": self.service_cluster.health_check_unhealthy_threshold,
                    "healthy_threshold": self.service_cluster.health_check_healthy_threshold,
                    "http_health_check": {
                        "path": SERVICE_PING_PAGES[self.service_cluster.service_type],
                    },
                }
            ]

        if self.is_service_https:
            cfg["transport_socket"] = {
                "name": "envoy.transport_sockets.tls",
                "typed_config": {"@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext"},
            }

        return cfg

    def get_xds_route_config(self):
        cfg = {
            "match": {"prefix": self.gateway_path},
            "route": {
                "prefix_rewrite": self.service_path,
                "cluster": self.envoy_cluster_name,
                "timeout": f"{get_preference_value('proxy', 'request_timeout')}s",
            },
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


class ServiceAPIRoute(Route, AuditableModel):
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


class AdditionalRoute(Route, AuditableModel):
    """
    Use this for configuring additional routes outside of the routes that are served from API_PREFIX.

    This model contains extra validation to ensure that custom routes don't conflict with the services
    that run on the api port.
    """

    router_basename = 'route'

    def clean(self):
        if self.http_port.is_api_port and self.gateway_path.startswith(API_PREFIX):
            raise ValidationError({"gateway_path": _("Custom routes on the API port cannot start with '%(API_PREFIX)s'") % {"API_PREFIX": API_PREFIX}})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
