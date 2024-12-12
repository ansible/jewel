from enum import Enum

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.db import models
from django.utils.translation import gettext as _


class ServiceType(UniqueNamedCommonModel, AuditableModel):
    """
    Allowable service types for platform services.
    """

    router_basename = 'service_type'

    ping_url = models.CharField(max_length=255, blank=False, null=False, help_text=_("URL to the ping/status page of the service, ex. /pulp/api/v3/status/"))

    login_path = models.CharField(max_length=255, blank=False, null=True, help_text=_("API path to login for service, ex. /v1/auth/session/login/"))

    logout_path = models.CharField(max_length=255, blank=False, null=True, help_text=_("API path to logout for service, ex. /logout/"))

    service_index_path = models.CharField(
        max_length=255, blank=False, null=True, help_text=_("API path to resource service index endpoint, ex. /v2/service-index/")
    )


class DefaultServiceType(str, Enum):
    """
    This is not meant to capture all possible service types that might be defined.
    There are places in the code that have special handling for the "built-in" types
    and to avoid using strings all over the place, this enum is used.  If more special
    handling for future service types is added, feel free to add to the enum.
    """

    GATEWAY = "gateway"
    CONTROLLER = "controller"
    EDA = "eda"
    HUB = "hub"
