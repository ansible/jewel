from rest_framework.permissions import BasePermission, IsAuthenticated

from aap_gateway_api.common.authentication import SERVICE_TOKEN_AUTH_STRING


class ServiceTokenAuthOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(IsAuthenticated().has_permission(request, view) and request.auth == SERVICE_TOKEN_AUTH_STRING)
