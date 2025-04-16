from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext as _

from aap_gateway_api.common.envoy import EXT_AUTH_FILTER, EXT_AUTH_PER_ROUTE
from aap_gateway_api.models.http_port import HTTPPort
from aap_gateway_api.models.service_cluster import ServiceCluster
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils.preferences import get_preference_value

API_PREFIX = "/api/"


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
        HTTPPort, related_name="routes", blank=False, on_delete=models.CASCADE, help_text=_("The port on the gateway to listen to traffic on.")
    )
    service_cluster = models.ForeignKey(ServiceCluster, related_name="routes", on_delete=models.CASCADE, help_text=_("The Ansible service to route traffic to."))

    service_port = models.IntegerField(
        blank=False, validators=[MaxValueValidator(65535), MinValueValidator(1)], help_text=_("The port on the service cluster to route traffic to.")
    )
    is_service_https = models.BooleanField(help_text=_("Set this to true if the service cluster requires HTTPS."))

    service_path = models.CharField(max_length=255, blank=False, help_text=_("The URL path on the Ansible service cluster to route traffic to."))
    gateway_path = models.CharField(max_length=255, blank=False, help_text=_("The path on the gateway to listen to traffic on."))

    description = models.CharField(max_length=255, blank=True, null=True, help_text=_('A description of this route.'))

    # Some routes, such as EDA webhooks, have their own authentication and my not need
    # gateway authentication tokens.
    enable_gateway_auth = models.BooleanField(default=True, help_text=_("If false, the gateway will not insert a gateway token into the proxied request."))
    # Some Routes should only be accessible to other gateway services, this flag indicates this
    is_internal_route = models.BooleanField(
        default=False, help_text=_("If true, the gateway will only allow other Ansible services to access this route. Requires gateway auth to be enabled.")
    )

    # Our setup here is a little bit weird. In the envoy model, ports are configured on the cluster object
    # but in this case we're configuring them on the route since all of the ports should be the same for every
    # ServiceNode. Because of that if multiple routes are configured for the same service on the same port,
    # they should point to the same cluster (which is a combination of ServiceCluster and Route). To avoid
    # creating a duplicate cluster with the same address/port combo, we're going to save a name for the
    # cluster in the db to identify the ServiceCluster/port combo.
    envoy_cluster_name = models.CharField(max_length=255, null=False, help_text=_("The name of the envoy cluster this route belongs to."))

    # The order of the routes
    order = models.IntegerField(
        default=50,
        validators=[MaxValueValidator(100), MinValueValidator(0)],
        help_text=_("The order to apply the routes in; lower numbers are first. Items with the same value have no guaranteed order"),
    )

    node_tags = models.CharField(
        max_length=255,
        blank=True,
        null=False,
        default="",
        help_text=_("A comma-separated list of nodes in the service cluster to receive traffic from this route.  Leave blank to select all nodes."),
    )

    def is_internal_route_string(self):
        return "t" if self.is_internal_route else "f"

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
            "type": self.service_cluster.dns_discovery_type,
            "lb_policy": "LEAST_REQUEST",
            "dns_lookup_family": self.service_cluster.dns_lookup_family,
            "load_assignment": {"cluster_name": self.envoy_cluster_name, "endpoints": [{"lb_endpoints": endpoints}]},
            "common_lb_config": {
                "healthy_panic_threshold": {
                    "value": self.service_cluster.healthy_panic_threshold,
                }
            },
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
                        "path": self.service_cluster.service_type.ping_url,
                    },
                }
            ]

        if self.is_service_https:
            cfg["transport_socket"] = {
                "name": "envoy.transport_sockets.tls",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                    "common_tls_context": {
                        "tls_params": {
                            "tls_maximum_protocol_version": "TLSv1_3",
                            "tls_minimum_protocol_version": "TLSv1_2",
                        },
                    },
                },
            }

            if self.service_cluster.upstream_hostname:
                cfg["transport_socket"]["typed_config"]["sni"] = self.service_cluster.upstream_hostname

        return cfg

    def get_xds_route_config(self):
        if not self.gateway_path or not self.service_path or not self.envoy_cluster_name:
            return []

        returned_routes = self.get_xds_login_logout_routes()

        cfg = {
            "match": {"prefix": self.gateway_path},
            "route": {
                "prefix_rewrite": self.service_path,
                "cluster": self.envoy_cluster_name,
                "timeout": f"{get_preference_value('proxy', 'request_timeout')}s",
            },
            "metadata": {
                "typed_filter_metadata": {},
            },
            "typed_per_filter_config": {},
        }

        if self.service_cluster.upstream_hostname:
            cfg["route"]["host_rewrite_literal"] = self.service_cluster.upstream_hostname

        if self.service_path != self.gateway_path:
            cfg["metadata"]["filter_metadata"] = {"envoy.filters.http.lua": {"prefix": self.gateway_path, "prefix_rewrite": self.service_path}}

            cfg["typed_per_filter_config"]["envoy.filters.http.lua"] = {
                "@type": "type.googleapis.com/envoy.extensions.filters.http.lua.v3.LuaPerRoute",
                "name": "rewrite.lua",
            }

        if not self.enable_gateway_auth:
            cfg["typed_per_filter_config"][EXT_AUTH_FILTER] = {
                "@type": EXT_AUTH_PER_ROUTE,
                "disabled": not self.enable_gateway_auth,
            }
        else:
            cfg["typed_per_filter_config"][EXT_AUTH_FILTER] = {
                "@type": EXT_AUTH_PER_ROUTE,
                "check_settings": {
                    # map<string, string> to be sent to auth server per route
                    "context_extensions": {
                        "is_internal_route": self.is_internal_route_string(),
                        "service_type": self.service_cluster.service_type.name,
                        "auth_type": self.service_cluster.auth_type,
                    },
                },
            }

        returned_routes.append(cfg)

        return returned_routes

    def get_xds_login_logout_routes(self) -> list:
        returned_routes = []

        # If we are a ServiceAPIRoute, reroute login requests to the gateway instead of the service
        if not self.enable_gateway_auth:
            return returned_routes

        envoy_cluster_name = None
        try:
            sc = ServiceCluster.objects.filter(service_type__name=DefaultServiceType.GATEWAY.value).first()
            gw_route = Route.objects.get(service_cluster=sc)
            envoy_cluster_name = gw_route.envoy_cluster_name
        except ServiceCluster.DoesNotExist:
            return returned_routes
        except Route.DoesNotExist:
            return returned_routes

        # Determine the login/logout URLs for this cluster type
        service_login_url = self.service_cluster.get_login_path(self.gateway_path)
        service_logout_url = self.service_cluster.get_logout_path(self.gateway_path)

        if service_login_url is not None:
            login_url = reverse('login')
            returned_routes.append(
                {
                    "match": {"prefix": service_login_url},
                    "route": {
                        "prefix_rewrite": login_url,
                        "cluster": envoy_cluster_name,
                    },
                    'metadata': {},
                    'typed_per_filter_config': {
                        EXT_AUTH_FILTER: {
                            "@type": EXT_AUTH_PER_ROUTE,
                            "check_settings": {
                                "context_extensions": {
                                    "is_internal_route": self.is_internal_route_string(),
                                    "service_type": self.service_cluster.service_type.name,
                                    "auth_type": self.service_cluster.auth_type,
                                },
                            },
                        },
                    },
                },
            )

        if service_logout_url is not None:
            # Get gateways login url
            logout_url = reverse('logout')

            returned_routes.append(
                {
                    "match": {"prefix": service_logout_url},
                    "route": {
                        "prefix_rewrite": logout_url,
                        "cluster": envoy_cluster_name,
                    },
                    'metadata': {},
                    'typed_per_filter_config': {
                        EXT_AUTH_FILTER: {
                            "@type": EXT_AUTH_PER_ROUTE,
                            "check_settings": {
                                "context_extensions": {
                                    "is_internal_route": self.is_internal_route_string(),
                                    "service_type": self.service_cluster.service_type.name,
                                    "auth_type": self.service_cluster.auth_type,
                                },
                            },
                        },
                    },
                },
            )

        return returned_routes
