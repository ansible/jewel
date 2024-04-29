# User must be imported first or else we end up with a circular import
from aap_gateway_api.models.user import User  # noqa: 401  # isort: skip

from ansible_base.rbac import permission_registry

from aap_gateway_api.models.organization import Organization  # noqa: 401
from aap_gateway_api.models.preference import Preference  # noqa: 401
from aap_gateway_api.models.service import AdditionalRoute, HTTPPort, Route, ServiceAPIRoute, ServiceCluster, ServiceNode  # noqa: 401
from aap_gateway_api.models.team import Team  # noqa: 401

permission_registry.register(Team, parent_field_name='organization')
permission_registry.register(Organization, parent_field_name=None)

permission_registry.track_relationship(Team, 'users', 'Team Member')
permission_registry.track_relationship(Team, 'admins', 'Team Admin')
permission_registry.track_relationship(Team, 'parents', 'Team Member')

permission_registry.track_relationship(Organization, 'users', 'Organization Member')
permission_registry.track_relationship(Organization, 'admins', 'Organization Admin')
