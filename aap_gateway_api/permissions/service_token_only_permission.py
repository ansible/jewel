from rest_framework.permissions import BasePermission, IsAuthenticated


class ServiceTokenAuthOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(IsAuthenticated().has_permission(request, view) and request.auth == "ServiceTokenAuth")
