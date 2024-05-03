from ansible_base.lib.routers import AssociationResourceRouter

from aap_gateway_api import views
from aap_gateway_api.views.api.v1.user import OrganizationUserViewSet


class DeprecatedUserViewSet(views.UserViewSet):
    deprecated = True


class DeprecatedTeamViewSet(views.UserViewSet):
    deprecated = True


router = AssociationResourceRouter()
router.register(
    r'users',
    views.UserViewSet,
    related_views={},
)
router.register(
    r'organizations',
    views.OrganizationViewSet,
    related_views={
        'teams': (views.TeamViewSet, 'teams'),
        'users': (OrganizationUserViewSet, 'users'),
        'admins': (OrganizationUserViewSet, 'admins'),
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
        'users': (DeprecatedUserViewSet, 'users'),
        'admins': (DeprecatedUserViewSet, 'admins'),
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
