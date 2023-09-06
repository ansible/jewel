import logging
from collections import OrderedDict

from django.contrib.auth.backends import ModelBackend

logger = logging.getLogger('aap.gateway.authentication.backend')

authentication_backends = OrderedDict()


class GatewayAuth(ModelBackend):
    def authenticate(self, request, username=None, password=None):
        for backend in authentication_backends.values():
            user = backend.authenticate(request, username=username, password=password)
            if user:
                return user

        return None


def build_all_authenticators():
    from aap_gateway_api.authentication.ldap.ldap_backends import build_ldap_authenticators

    build_ldap_authenticators()
