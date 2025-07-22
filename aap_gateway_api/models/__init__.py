# User must be imported first or else we end up with a circular import
from aap_gateway_api.models.user import User, MigratedUserMetadata  # noqa: 401  # isort: skip

from ansible_base.rbac import permission_registry

from aap_gateway_api.models.organization import Organization  # noqa: 401
from aap_gateway_api.models.preference import Preference  # noqa: 401
from aap_gateway_api.models.route import Route  # noqa: 401
from aap_gateway_api.models.service_api_route import ServiceAPIRoute  # noqa: 401
from aap_gateway_api.models.service_auth import ServiceKey  # noqa: 401
from aap_gateway_api.models.service_node import ServiceNode  # noqa: 401
from aap_gateway_api.models.service_type import DefaultServiceType, ServiceType  # noqa: 401
from aap_gateway_api.models.team import Team  # noqa: 401
from aap_gateway_api.models.ui_plugin_route import UIPluginRoute  # noqa: 401

# Skip isort for the below to prevent circular imports caused by the alphabetical sorting of these imports.
from aap_gateway_api.models.additional_route import AdditionalRoute  # noqa: 401  # isort: skip
from aap_gateway_api.models.http_port import HTTPPort  # noqa: 401  # isort: skip
from aap_gateway_api.models.service_cluster import ServiceCluster  # noqa: 401  # isort: skip

permission_registry.register(Team, parent_field_name='organization')
permission_registry.register(Organization, parent_field_name=None)
