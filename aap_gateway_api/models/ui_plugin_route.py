from ansible_base.activitystream.models import AuditableModel
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models.route import Route
from aap_gateway_api.models.service_cluster import ServiceCluster

PLUGIN_PREFIX = "/plugin/"


class UIPluginRoute(Route, AuditableModel):
    router_basename = 'ui_plugin_route'

    ui_plugin_path = models.CharField(
        max_length=255,
        help_text=_("The relative path to the UI plugin on the service cluster."),
        blank=False,
    )

    def save(self, *args, **kwargs):
        service_cluster_name = ServiceCluster.objects.get(id=self.service_cluster.id).name
        # On a single HTTP port, you cannot have multiple routes pointing to the same plugin on a service cluster.
        # appending a unique service cluster name to the path ensures that the route is unique and different service
        # clusters can have the same plugin path.
        self.gateway_path = PLUGIN_PREFIX + service_cluster_name + "/" + self.ui_plugin_path + "/"
        self.enable_gateway_auth = False
        self.is_internal_route = False

        self.service_path = self.ui_plugin_path

        return super().save(*args, **kwargs)

    def get_xds_login_logout_routes(self) -> list:
        # UI plugins don't need their own login/logout routes
        # Authentication is handled by the parent service
        return []

    def get_xds_route_config(self):
        self.service_path = self.ui_plugin_path
        routes = super().get_xds_route_config()

        return routes
