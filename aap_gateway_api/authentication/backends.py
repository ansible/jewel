import logging
from collections import OrderedDict

from django.contrib.auth.backends import ModelBackend

from aap_gateway_api.authentication.common import create_claims
from aap_gateway_api.authentication.ldap.backends import BaseLDAPBackend, LDAPSettings
from aap_gateway_api.models import Authenticator

logger = logging.getLogger('aap.gateway.authentication.backend')

authentication_backends = OrderedDict()


class GatewayAuth(ModelBackend):
    def authenticate(self, request, username=None, password=None):
        for backend in Authenticator.objects.filter(type='l', enabled=True):
            self.create_or_update_ldap_adapter(backend)
            user, attrs, groups = authentication_backends[backend.id].authenticate(request, username=username, password=password)
            if user:
                results = create_claims(backend, user.username, attrs, groups)
                needs_save = False
                for attribute, attr_value in results.items():
                    logger.debug(f"{attribute}: {attr_value}")
                    if getattr(user, attribute) != attr_value:
                        logger.debug(f"Setting new attribute {attribute} for {user.username}")
                        setattr(user, attribute, attr_value)
                        needs_save = True

                if needs_save:
                    logger.info(f"Saving user {user.username}")
                    user.save()

                if results['access_allowed'] is not True:
                    logger.warning(f"User {user.username} failed an allow map and was denied access")
                    return None
                return user

        return None

    def create_or_update_ldap_adapter(self, authenticator):
        needs_change = False
        if authenticator.id not in authentication_backends:
            logger.info(f"Creating LDAP adapter for {authenticator.name}")
            authentication_backends[authenticator.id] = BaseLDAPBackend(authenticator=authenticator)
            needs_change = True

        if needs_change or authenticator.modified_on != authentication_backends[authenticator.id].authenticator.modified_on:
            if not needs_change:
                logger.info(f"Updating LDAP adapter {authenticator.name}")

            authentication_backends[authenticator.id].settings = LDAPSettings(defaults=authenticator.configuration)
            authentication_backends[authenticator.id].authenticator = authenticator
        else:
            logger.info(f"No updated needed for LDAP adapter {authenticator.name}")
