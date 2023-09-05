import logging

from django.contrib import admin
from django.urls import path, re_path

from aap_gateway_api import views

logger = logging.getLogger('aap.gateway.urls')

list_actions = {'get': 'list', 'post': 'create'}
detail_actions = {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}
view_only_list = {'get': 'list'}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', views.ApiRootView.as_view(), name='api_root_view'),
    path('api/gateway/', views.GatewayRootView.as_view(), name='api_gateway_root_view'),
    path('api/gateway/v1/', views.V1RootView.as_view(), name='api_gateway_v1_root_view'),
    path('api/gateway/v1/jwt_key/', views.JWTKeyView.as_view()),
    path(
        'api/gateway/v1/login/',
        views.LoggedLoginView.as_view(template_name='rest_framework/login.html', extra_context={'inside_login_context': True}),
        name='login',
    ),
    path('api/gateway/v1/logout/', views.LoggedLogoutView.as_view(next_page='/api/', redirect_field_name='next'), name='logout'),
    path('api/gateway/v1/environments/', views.EnvironmentViewSet.as_view(list_actions), name='environment-list'),
    re_path(r'api/gateway/v1/environments/(?P<pk>[0-9]+)/$', views.EnvironmentViewSet.as_view(detail_actions), name='environment-detail'),
    re_path(
        r'api/gateway/v1/environments/(?P<pk>[0-9]+)/organizations/$',
        views.EnvironmentOrganizationViewSet.as_view(view_only_list),
        name='environment-organizations',
    ),
    re_path(r'api/gateway/v1/environments/(?P<pk>[0-9]+)/services/$', views.EnvironmentServiceViewSet.as_view(view_only_list), name='environment-services'),
    path('api/gateway/v1/me', views.MeViewSet.as_view(view_only_list), name='me-list'),
    path('api/gateway/v1/organizations/', views.OrganizationViewSet.as_view(list_actions), name='organization-list'),
    re_path(r'api/gateway/v1/organizations/(?P<pk>[0-9]+)/$', views.OrganizationViewSet.as_view(detail_actions), name='organization-detail'),
    re_path(r'api/gateway/v1/organizations/(?P<pk>[0-9]+)/teams/$', views.OrganizationTeamViewSet.as_view(view_only_list), name='organization-teams'),
    path('api/gateway/v1/services/', views.ServiceViewSet.as_view(list_actions), name='service-list'),
    re_path(r'api/gateway/v1/services/(?P<pk>[0-9]+)/$', views.ServiceViewSet.as_view(detail_actions), name='service-detail'),
    path('api/gateway/v1/settings/', views.PreferenceListView.as_view(view_only_list), name='settings-list'),
    re_path(r'api/gateway/v1/settings/(?P<category_slug>[a-z0-9-]+)/$', views.PreferenceSingletonView.as_view(), name='setting-section-list'),
    path('api/gateway/v1/teams/', views.TeamViewSet.as_view(list_actions), name='team-list'),
    re_path(r'api/gateway/v1/teams/(?P<pk>[0-9]+)/$', views.TeamViewSet.as_view(detail_actions), name='team-detail'),
    path('api/gateway/v1/user/', views.UserViewSet.as_view(list_actions), name='user-list'),
    re_path(r'api/gateway/v1/users/(?P<pk>[0-9]+)/$', views.UserViewSet.as_view(detail_actions), name='user-detail'),
]
