import logging

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.legacy_sso')


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    configuration_class = BaseAuthenticatorConfiguration
    logger = logger
    type = "legacy_sso"
    category = "legacy"

    # This authenticator doesn't actually do anything. It's just a placeholder
    # that allows an admin to match up legacy users with newly configured authenticator
    # plugins.
    def authenticate(self, request, username=None, password=None, **kwargs):
        return None
