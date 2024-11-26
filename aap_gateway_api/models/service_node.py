from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.db import models
from django.utils.translation import gettext as _

from aap_gateway_api.models.service_cluster import ServiceCluster


class ServiceNode(UniqueNamedCommonModel, AuditableModel):
    """
    Individual node in a service cluster.
    """

    router_basename = 'service_node'

    class Meta:
        models.UniqueConstraint("address", name="one_address_per_gateway")

    service_cluster = models.ForeignKey(
        ServiceCluster, related_name='nodes', on_delete=models.CASCADE, help_text=_("The Ansible service cluster that this node belongs to.")
    )
    address = models.CharField(max_length=255, help_text=_("The network address to route traffic for this service to."))
    tags = models.CharField(
        max_length=255,
        blank=True,
        null=False,
        default="",
        help_text=_("A comma-separated list of roles to assign to a node; to be selective about which routes point to it."),
    )

    def tags_list(self):
        return [tag.strip() for tag in self.tags.split(",")] if self.tags else []
