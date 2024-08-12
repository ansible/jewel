from rest_framework.permissions import SAFE_METHODS, BasePermission

from aap_gateway_api.exceptions import ProxyDenied
from aap_gateway_api.utils.requests import from_proxy


class DisallowWriteFromProxy(BasePermission):
    """
    Disallow gateway-breaking writes from proxied requests
    """

    def has_object_permission(self, request, view, obj):
        if from_proxy(request) and request.method not in SAFE_METHODS and view.object_write_unsafe(request, obj):
            raise ProxyDenied()
        return True
