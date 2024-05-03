import logging

from ansible_base.lib.dynamic_config.dynamic_urls import api_urls, api_version_urls, root_urls
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from django.contrib import admin
from django.urls import include, path, re_path

from aap_gateway_api import views
from aap_gateway_api.router import router
from aap_gateway_api.views.api.envoy.rest_control_plane import ClusterDiscoverServiceView, ListenerDiscoverServiceView

logger = logging.getLogger('aap.gateway.urls')


urlpatterns = [
    # Load base URLs first
    path('api/gateway/v1/', include(api_version_urls)),
    path('api/gateway/', include(api_urls)),
    path('', include(root_urls)),
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
    re_path(r'api/gateway/v1/settings/(?P<category_slug>[a-z0-9_]+)/$', views.PreferenceSingletonView.as_view(), name='setting-section-list'),
    # xDS
    path('v3/discovery:listeners', ListenerDiscoverServiceView.as_view(), name='lds'),
    path('v3/discovery:clusters', ClusterDiscoverServiceView.as_view(), name='cds'),
    # Social auth
    path('api/gateway/v1/', include(router.urls)),
    path('api/gateway/v1/', include(resource_api_urls)),
]
