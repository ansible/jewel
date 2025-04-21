import logging

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration

from aap_gateway_api.authentication.authenticator_plugins.base import LegacyMixin

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.legacy_password')


class AuthenticatorPlugin(LegacyMixin, AbstractAuthenticatorPlugin):
    configuration_class = BaseAuthenticatorConfiguration
    logger = logger
    type = "legacy_password"
    category = "legacy"
