from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException


class ProxyDenied(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = _('Action not allowed from proxy')
    default_code = 'permission_denied'
