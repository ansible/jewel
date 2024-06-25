from ansible_base.lib.routers import AssociationResourceRouter

from aap_gateway_api import views
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
    views.PreferenceListViewSet,
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
    },
)
router.register(
    r'routes',
    views.AdditionalRouteViewSet,
    basename='route',
)
