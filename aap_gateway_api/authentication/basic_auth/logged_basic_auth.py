import logging

from django.utils.encoding import smart_str
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication

from aap_gateway_api.utils import get_preference_value

logger = logging.getLogger('aap.gateway.authentication.basic_auth')


class LoggedBasicAuthentication(authentication.BasicAuthentication):
    def authenticate(self, request):
        if not get_preference_value('proxy', 'gateway_basic_auth_enabled'):
            return
        ret = super(LoggedBasicAuthentication, self).authenticate(request)
        if ret:
            username = ret[0].username if ret[0] else '<none>'
            logger.info(smart_str(f"User {username} performed a {request.method} to {request.path} through the API via basic auth"))
        return ret

    def authenticate_header(self, request):
        if not get_preference_value('proxy', 'gateway_basic_auth_enabled'):
            return
        return super(LoggedBasicAuthentication, self).authenticate_header(request)


class LoggedBasicAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'aap_gateway_api.authentication.basic_auth.logged_basic_auth.LoggedBasicAuthentication'
    name = 'Basic_Authentication'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'basic',
        }
