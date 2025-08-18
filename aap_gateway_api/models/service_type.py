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

    ping_url = models.CharField(max_length=255, blank=False, null=True, help_text=_("URL to the ping/status page of the service, ex. /pulp/api/v3/status/"))

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

    @staticmethod
    def is_default(name: str) -> bool:
        return any(svc.value == name for svc in DefaultServiceType)


class StreamingServiceType(str, Enum):
    """
    Service types that support streaming responses and require special timeout handling.
    """

    LIGHTSPEED = "lightspeed"

    @staticmethod
    def is_streaming_service(name: str) -> bool:
        """Check if a service type supports streaming responses."""
        return any(svc.value == name for svc in StreamingServiceType)


def get_service_type_name(service_type: str) -> str:
    """
    Normalize service type names for legacy compatibility.

    This function is needed because ServiceType.name stores normalized values
    ('gateway', 'controller', 'eda', 'hub') but legacy systems may still
    reference services using old names like 'awx' and 'galaxy'.

    Maps legacy service type names to their current equivalents:
    - "awx" -> "controller"
    - "galaxy" -> "hub"

    Args:
        service_type: The service type name to normalize

    Returns:
        str: The normalized service type name matching ServiceType.name values
    """
    # Ensure service_type is a string
    if not isinstance(service_type, str):
        service_type = str(service_type)

    # Preserve coercion of awx -> controller and galaxy -> hub
    if service_type.casefold() == "awx".casefold():
        return DefaultServiceType.CONTROLLER.value
    elif service_type.casefold() == "galaxy".casefold():
        return DefaultServiceType.HUB.value
    else:
        return service_type


def service_type_to_api_slug(service_type: str) -> str:
    """
    Convert service type names to API route slugs.

    This function is needed because ServiceType.name values don't always
    match ServiceAPIRoute.api_slug values. The resource registry and
    RBAC systems use service type names, but API routing uses different slugs
    for historical reasons.

    Maps service types to their corresponding API slugs:
    - ServiceType.name: ['gateway', 'controller', 'eda', 'hub']
    - ServiceAPIRoute.api_slug: ['gateway', 'controller', 'eda', 'galaxy']
    - Legacy 'awx' -> 'controller'

    This converts the first part of dab_resource_registry.ResourceType.name
    (split on period, like 'awx.inventory') and dab_rbac.DABContentType.service
    to the appropriate ServiceAPIRoute.api_slug value.

    Args:
        service_type: The service type name from resource registry/RBAC

    Returns:
        str: The API slug for routing purposes
    """
    # Preserve coercion of awx -> controller
    if service_type.casefold() == "awx".casefold():
        return DefaultServiceType.CONTROLLER.value
    else:
        return service_type
