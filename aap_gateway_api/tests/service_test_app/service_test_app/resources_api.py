import os

from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, RoleDefinitionType, TeamType, UserType
from service_test_app.models import Organization, Team, User


class APIConfig(ServiceAPIConfig):
    service_type = os.environ.get("SERVICE_TEST_APP_TYPE", "aap")


RESOURCE_LIST = (
    ResourceConfig(User, shared_resource=SharedResource(serializer=UserType, is_provider=False), name_field="username"),
    ResourceConfig(
        Team,
        shared_resource=SharedResource(serializer=TeamType, is_provider=False),
    ),
    ResourceConfig(
        Organization,
        shared_resource=SharedResource(serializer=OrganizationType, is_provider=False),
    ),
    ResourceConfig(RoleDefinition, shared_resource=SharedResource(serializer=RoleDefinitionType, is_provider=False)),
)
