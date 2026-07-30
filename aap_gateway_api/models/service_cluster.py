import logging
from datetime import datetime
from typing import Optional

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.resource_registry.models import service_id
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Max
from django.utils.translation import gettext as _

from aap_gateway_api.models.service_type import DefaultServiceType, ServiceType
from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger(__name__)


class ServiceCluster(UniqueNamedCommonModel, AuditableModel):
    """
    Represents an Ansible service which can be comprised of multiple load balanced nodes.
    """

    router_basename = 'service_cluster'

    service_type = models.ForeignKey(
        ServiceType, related_name='clusters', on_delete=models.CASCADE, help_text=_("The Ansible service type of this service cluster.")
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
        default=100,
        validators=[
            MaxValueValidator(100),
            MinValueValidator(0),
        ],
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
        default=30,
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

    healthy_panic_threshold = models.PositiveIntegerField(
        default=0,
        validators=[
            MaxValueValidator(100),
            MinValueValidator(0),
        ],
        help_text=_("The percentage of failed hosts when the proxy will panic and start routing traffic to all nodes. Set to 0 to disable this."),
    )

    class ServiceAuthType(models.TextChoices):
        JWT_AUTH = "JWT", "JWT"
        BASIC_AUTH = "BASIC", "Basic auth"
        TOKEN_AUTH = "TOKEN", "Bearer token"

    auth_type = models.CharField(
        choices=ServiceAuthType.choices,
        default=ServiceAuthType.JWT_AUTH,
        max_length=255,
        null=False,
        blank=False,
        help_text=_("The authorization type for this service."),
    )

    upstream_hostname = models.CharField(
        default="", max_length=255, null=False, blank=True, help_text=_("Set this value to enable server name identification on associated routes.")
    )

    class DNSServiceDiscovery(models.TextChoices):
        LOGICAL_DNS = "LOGICAL_DNS", "Logical DNS"
        STRICT_DNS = "STRICT_DNS", "Strict DNS"

    dns_discovery_type = models.CharField(
        choices=DNSServiceDiscovery.choices,
        default=DNSServiceDiscovery.STRICT_DNS,
        max_length=255,
        null=False,
        blank=False,
        help_text=_("The DNS service discovery type for this service."),
    )

    class DNSLookupFamily(models.TextChoices):
        V4_ONLY = "V4_ONLY", "IPv4 only"
        V6_ONLY = "V6_ONLY", "IPv6 only"
        AUTO = "AUTO", "Auto (IPv6 preferred)"
        ALL = "ALL", "All IPv4 and IPv6 addresses"
        V4_PREFERRED = "V4_PREFERRED", "IPv4 preferred"

    dns_lookup_family = models.CharField(
        choices=DNSLookupFamily.choices, default=DNSLookupFamily.ALL, max_length=255, null=False, blank=False, help_text=_("DNS lookup type for this service.")
    )

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        response['service_type'] = self.service_type.id
        return response

    def __str__(self):
        return self.service_type.name

    def save(self, *args, **kwargs):
        # Set the service id for the gateway.
        if self.service_type.name == DefaultServiceType.GATEWAY and not self.service_id:
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

    def _get_auth_path(self, url_prefix: str, path_attr: str) -> Optional[str]:
        url_prefix = url_prefix.rstrip('/')
        path = getattr(self.service_type, path_attr)
        if self.service_type.name in [DefaultServiceType.CONTROLLER, DefaultServiceType.EDA]:
            return f"{url_prefix}{path}"
        elif self.service_type.name in [DefaultServiceType.HUB]:
            return f"{path}"
        else:
            return None

    def get_login_path(self, url_prefix: str) -> Optional[str]:
        return self._get_auth_path(url_prefix, 'login_path')

    def get_logout_path(self, url_prefix: str) -> Optional[str]:
        return self._get_auth_path(url_prefix, 'logout_path')

    def get_effective_health_check_timeout_seconds(self):
        # _max_route_timeout may be pre-populated as a queryset annotation by
        # ServiceClusterViewSet.get_queryset() to avoid an N+1 query on list
        # responses. When absent we fall back to a per-object aggregate.
        if hasattr(self, '_max_route_timeout'):
            max_route_timeout = self._max_route_timeout or 0
        else:
            max_route_timeout = (
                (self.routes.exclude(request_timeout_seconds__isnull=True).aggregate(max_timeout=Max('request_timeout_seconds'))['max_timeout']) or 0
            )
        return max(
            self.health_check_timeout_seconds,
            max_route_timeout,
            get_preference_value('proxy', 'request_timeout'),
        )

    def get_effective_health_check_interval_seconds(self, effective_timeout=None):
        if effective_timeout is None:
            effective_timeout = self.get_effective_health_check_timeout_seconds()
        effective_interval = max(self.health_check_interval_seconds, effective_timeout)
        if effective_interval != self.health_check_interval_seconds:
            logger.debug(
                "Health check interval for cluster %s floored from %ds to %ds (effective timeout)",
                self.name,
                self.health_check_interval_seconds,
                effective_interval,
            )
        return effective_interval

    @staticmethod
    def get_cluster_by_type(service_type: ServiceType | str):
        if isinstance(service_type, ServiceType):
            return ServiceCluster.objects.filter(service_type=service_type).first()
        return ServiceCluster.objects.filter(service_type__name=service_type).first()
