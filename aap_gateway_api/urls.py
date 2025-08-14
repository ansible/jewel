import logging

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.lib.utils.converters import IntOrUUIDConverter
from ansible_base.rbac.api.views import RoleMetadataView, TeamAccessAssignmentViewSet, TeamAccessViewSet, UserAccessAssignmentViewSet, UserAccessViewSet
from ansible_base.rbac.service_api.urls import rbac_service_urls
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path, register_converter

from aap_gateway_api import views
from aap_gateway_api.router import router
from aap_gateway_api.views.api.envoy.rest_control_plane import ClusterDiscoverServiceView, ListenerDiscoverServiceView

logger = logging.getLogger('aap.gateway.urls')


user_access_view = UserAccessViewSet.as_view({'get': 'list'})
team_access_view = TeamAccessViewSet.as_view({'get': 'list'})
user_access_assignment_view = UserAccessAssignmentViewSet.as_view({'get': 'list'})
team_access_assignment_view = TeamAccessAssignmentViewSet.as_view({'get': 'list'})

register_converter(IntOrUUIDConverter, "int_or_uuid")

urlpatterns = [
    # Load base URLs first
    path('api/gateway/v1/', include(api_version_urls)),
    path('api/gateway/', include(api_urls)),
    path('', include(root_urls)),
    # Extra DAB RBAC views that need to be included because we exclude it from api_version_urls
    path(r'role_metadata/', RoleMetadataView.as_view(), name="role-metadata"),
    path('api/gateway/v1/role_user_access/<str:model_name>/<int_or_uuid:pk>/', user_access_view, name="role-user-access"),
    path('api/gateway/v1/role_team_access/<str:model_name>/<int_or_uuid:pk>/', team_access_view, name="role-team-access"),
    path(
        'api/gateway/v1/role_user_access/<str:model_name>/<int_or_uuid:pk>/<str:actor_pk>/',
        user_access_assignment_view,
        name='role-user-access-assignments',
    ),
    path(
        'api/gateway/v1/role_team_access/<str:model_name>/<int_or_uuid:pk>/<str:actor_pk>/',
        team_access_assignment_view,
        name='role-team-access-assignments',
    ),
    path('admin/', admin.site.urls),
    path('api/', views.ApiRootView.as_view(), name='api_root_view'),
    path('api/gateway/', views.GatewayRootView.as_view(), name='api_gateway_root_view'),
    path('api/gateway/v1/', views.V1RootView.as_view(), name='api_gateway_v1_root_view'),
    path('api/gateway/v1/jwt_key/', views.JWTKeyView.as_view(), name='jwt-key-view'),
    path('api/gateway/v1/ping/', views.PingView.as_view(), name='ping-view'),
    path('api/gateway/v1/status/', views.StatusView.as_view(), name='status-view'),
    re_path('api/gateway/v1/users/(?P<pk>[0-9]+)/teams/', views.UserTeamViewSet.as_view({'get': 'list'}), name='user-teams-list'),
    re_path('api/gateway/v1/users/(?P<pk>[0-9]+)/organizations/', views.UserOrganizationViewSet.as_view({'get': 'list'}), name='user-organizations-list'),
    path(
        'api/gateway/v1/login/',
        views.LoggedLoginView.as_view(template_name='rest_framework/login.html', extra_context={'inside_login_context': True}),
        name='login',
    ),
    path('api/gateway/v1/logout/', views.LoggedLogoutView.as_view(next_page='/api/', redirect_field_name='next'), name='logout'),
    path('api/gateway/v1/me/', views.MeViewSet.as_view({'get': 'list'}), name='me-list'),
    path('api/gateway/v1/session/', views.SessionView.as_view(), name='session-view'),
    # settings
    re_path(r'api/gateway/v1/settings/(?P<category_slug>[a-z0-9_]+)/$', views.SettingSectionView.as_view(), name='setting-section-list'),
    re_path(
        r'^api/gateway/v1/settings/(?P<category_slug>[a-z0-9_]+)/(?P<preference_name>[a-zA-Z0-9_]+)/$',
        views.SettingPreferenceView.as_view(),
        name='setting-detail',
    ),
    # xDS
    path('v3/discovery:listeners', ListenerDiscoverServiceView.as_view(), name='lds'),
    path('v3/discovery:clusters', ClusterDiscoverServiceView.as_view(), name='cds'),
    # Social auth
    path('api/gateway/v1/', include(router.urls)),
    path('api/gateway/v1/', include(resource_api_urls)),
    path('api/gateway/v1/', include(rbac_service_urls)),
    # JWT claims endpoint
    path('api/gateway/v1/jwt_claims/<str:user_ansible_id>/', views.JWTClaimsView.as_view(), name='jwt-claims-view'),
]

if getattr(settings, 'ENABLE_DJANGO_DEBUG_TOOLBAR', False):
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns.extend(debug_toolbar_urls())
