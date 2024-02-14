from ansible_base.lib.routers import AssociationResourceRouter

from aap_gateway_api import views

router = AssociationResourceRouter()
router.register(
    r'users',
    views.UserViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'organizations': (views.OrganizationViewSet, 'organizations'),
    },
)
router.register(
    r'environments',
    views.EnvironmentViewSet,
    related_views={
        'organizations': (views.OrganizationViewSet, 'organizations'),
    },
)
router.register(
    r'organizations',
    views.OrganizationViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'users': (views.UserViewSet, 'users'),
        'admins': (views.UserViewSet, 'admins'),
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
        'users': (views.UserViewSet, 'users'),
        'admins': (views.UserViewSet, 'admins'),
        'parents': (views.TeamViewSet, 'parents'),
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
    },
)
router.register(
    r'routes',
    views.AdditionalRouteViewSet,
    basename='route',
)
