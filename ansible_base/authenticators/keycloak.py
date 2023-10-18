import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from social_core.backends.keycloak import KeycloakOAuth2

from ansible_base.authentication.authenticator_lib import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration, SocialAuthMixin, URLField

logger = logging.getLogger('ansible_base.authentication.authenticators.keycloak')


class KeycloakConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://python-social-auth.readthedocs.io/en/latest/backends/keycloak.html"

    ACCESS_TOKEN_URL = URLField(
        help_text=_("Location where this app can fetch the user's token from."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/token",
        allow_null=False,
    )
    AUTHORIZATION_URL = URLField(
        help_text=_("Location to redirect the user to during the login flow."),
        default="https://keycloak.example.com/auth/realms/<my_realm>/protocol/openid-connect/auth",
        allow_null=False,
    )
    KEY = serializers.CharField(help_text=_("Keycloak Client ID."), allow_null=False)
    PUBLIC_KEY = serializers.CharField(help_text=_("RS256 public key provided by your Keycloak ream."), allow_null=False)
    SECRET = serializers.CharField(help_text=_("Keycloak Client secret."), allow_null=True)
    VERIFY_SSL = serializers.BooleanField(help_text=_("Validate the Keycloak certificate"), allow_null=False, default=True)


class AuthenticatorPlugin(SocialAuthMixin, KeycloakOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = KeycloakConfiguration
    type = "keycloak"
    logger = logger
    category = "sso"
