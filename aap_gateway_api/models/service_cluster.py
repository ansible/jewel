from datetime import datetime

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.resource_registry.models import service_id
from django.db import models
from django.utils.translation import gettext as _

from aap_gateway_api.utils.resources_client import ServiceTypeChoices


class ServiceCluster(UniqueNamedCommonModel, AuditableModel):
    """
    Represents an AAP Service which can be comprised of multiple load balanced nodes.
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

    service_id = models.UUIDField(unique=True, help_text="The unique service ID provided by the service.", null=True, editable=False)

    outlier_detection_enabled = models.BooleanField(
        default=True,
        help_text=_("If true, outlier detection will be used to determine if a node is unhealthy and should be ejected from the cluster."),
    )

    outlier_detection_consecutive_5xx = models.PositiveIntegerField(
        default=5,
        help_text=_("The number of consecutive 5xx responses to consider a node unhealthy."),
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
        # Set the service id for the Gateway.
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
