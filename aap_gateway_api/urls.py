"""
URL configuration for project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from aap_gateway_api.views.api import (
    EnvironmentViewSet,
    LoggedLoginView,
    LoggedLogoutView,
    MeViewSet,
    OrganizationViewSet,
    ServiceViewSet,
    TeamViewSet,
    UserViewSet,
)
from aap_gateway_api.views.jwt_key import JWTKeyView

router = routers.DefaultRouter()
router.register(r'environment', EnvironmentViewSet)
router.register(r'organization', OrganizationViewSet)
router.register(r'service', ServiceViewSet)
router.register(r'team', TeamViewSet)
router.register(r'user', UserViewSet)
router.register(r'me', MeViewSet, basename='me')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/gateway/v1/jwt_key/', JWTKeyView.as_view()),
    path('api/gateway/v1/', include(router.urls)),
    path(
        'api/gateway/v1/login/', LoggedLoginView.as_view(template_name='rest_framework/login.html', extra_context={'inside_login_context': True}), name='login'
    ),
    path('api/gateway/v1/logout/', LoggedLogoutView.as_view(next_page='/api/', redirect_field_name='next'), name='logout'),
]
