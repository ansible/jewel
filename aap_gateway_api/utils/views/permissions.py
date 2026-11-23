from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission

from aap_gateway_api.exceptions import ProxyDenied
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.utils.requests import from_proxy


class ApiRootAccessPermission(OAuth2ScopePermission):
    """Allow anonymous access to API roots unless API_ROOTS_REQUIRE_AUTHENTICATION is enabled."""

    def has_permission(self, request, view):
        if getattr(settings, 'API_ROOTS_REQUIRE_AUTHENTICATION', False):
            return super().has_permission(request, view)
        return True


class DisallowWriteFromProxy(BasePermission):
    """
    Disallow gateway-breaking writes from proxied requests
    """

    def has_object_permission(self, request, view, obj):
        if from_proxy(request) and request.method not in SAFE_METHODS and view.object_write_unsafe(request, obj):
            raise ProxyDenied()
        return True


class IsSuperuserOrManageOrgsEnabled(BasePermission):
    """
    Allow safe (read-only) methods unconditionally.
    For write methods, require that the user is a superuser or
    MANAGE_ORGANIZATION_AUTH is enabled.
    """

    message = "This action is disabled when MANAGE_ORGANIZATION_AUTH is false."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        return get_preference_value('configuration', 'MANAGE_ORGANIZATION_AUTH')
