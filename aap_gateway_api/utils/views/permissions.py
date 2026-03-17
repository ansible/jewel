from rest_framework.permissions import SAFE_METHODS, BasePermission

from aap_gateway_api.exceptions import ProxyDenied
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.utils.requests import from_proxy


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
