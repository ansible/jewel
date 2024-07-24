from rest_framework.permissions import SAFE_METHODS, BasePermission

from aap_gateway_api.utils.requests import from_proxy


class DisallowWriteFromProxy(BasePermission):
    """
    Disallow write from proxied requests
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return not from_proxy(request)
