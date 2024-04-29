import logging

from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from aap_gateway_api.utils.rbac import get_system_auditor_role

logger = logging.getLogger('aap.gateway.permissions')


class IsSystemAdminOrAuditor(permissions.BasePermission):
    """
    Allows write access only to system admin users.
    Allows read access only to system auditor users.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        if request.method in SAFE_METHODS:
            auditor_role = get_system_auditor_role()
            return request.user.has_roles.filter(role_definition=auditor_role).exists()
        return False
