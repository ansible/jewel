from ansible_base.lib.routers import AssociationResourceRouter

from aap_gateway_api import views
from aap_gateway_api.views.api.v1 import role as rbac_views
from aap_gateway_api.views.api.v1.user import OrganizationRelatedUserViewSet, TeamRelatedUserViewSet

router = AssociationResourceRouter()
router.register(
    r'users',
    views.UserViewSet,
    related_views={},
)
router.register(
    r'service_keys',
    views.ServiceKeyViewSet,
    basename='service_key',
)
router.register(
    r'organizations',
    views.OrganizationViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'users': (OrganizationRelatedUserViewSet, 'users'),
        'admins': (OrganizationRelatedUserViewSet, 'admins'),
    },
)
router.register(
    r'services',
    views.ServiceAPIRouteViewSet,
    basename='service',
)
router.register(
    r'settings',
    views.SettingSectionViewSet,
    basename='setting',
)
router.register(
    r'teams',
    views.TeamViewSet,
    related_views={
        'users': (TeamRelatedUserViewSet, 'users'),
        'admins': (TeamRelatedUserViewSet, 'admins'),
    },
)
router.register(
    r'service_nodes',
    views.ServiceNodeViewSet,
    basename='service_node',
)
router.register(
    r'service_types',
    views.ServiceTypeViewSet,
    basename='service_type',
    related_views={
        'clusters': (views.ServiceClusterViewSet, 'clusters'),
    },
)
router.register(
    r'ui_plugin_routes',
    views.UIPluginRouteViewSet,
    basename='ui_plugin_route',
)
router.register(
    r'http_ports',
    views.HTTPPortViewSet,
    basename='http_port',
    related_views={
        'routes': (views.AdditionalRouteViewSet, 'routes'),
    },
)
router.register(
    r'service_clusters',
    views.ServiceClusterViewSet,
    basename='service_cluster',
    related_views={
        'routes': (views.AdditionalRouteViewSet, 'routes'),
        'nodes': (views.ServiceNodeViewSet, 'nodes'),
        'service_keys': (views.ServiceKeyViewSet, 'service_keys'),
        'service_types': (views.ServiceTypeViewSet, 'service_types'),
    },
)
router.register(
    r'routes',
    views.AdditionalRouteViewSet,
    basename='route',
)

router.register(
    r'authenticator_users',
    views.AuthenticatorUserViewSet,
    basename='authenticator_user',
)
router.register(
    r'app_urls',
    views.AppUrlViewSet,
    basename='app_url',
)

# Add the Gateway-overwritten version of role definitions
router.register(
    r'role_definitions',
    rbac_views.GatewayRoleDefinitionViewSet,
    related_views={
        'user_assignments': (rbac_views.GatewayRoleUserAssignmentViewSet, 'user_assignments'),
        'team_assignments': (rbac_views.GatewayRoleTeamAssignmentViewSet, 'team_assignments'),
    },
    basename='roledefinition',
)
router.register(r'role_user_assignments', rbac_views.GatewayRoleUserAssignmentViewSet, basename='roleuserassignment')
router.register(r'role_team_assignments', rbac_views.GatewayRoleTeamAssignmentViewSet, basename='roleteamassignment')
router.register(
    r'ca_certificates',
    views.CACertificateViewSet,
    basename='ca_certificate',
)

router.register(r'feature_flags', views.AAPFlagViewSet, basename='aap_flag')
