from ansible_base.lib.backends.prefixed_user_auth import PrefixedUserAuthenticationMixin
from django.contrib.auth.backends import ModelBackend
from social_core.backends.keycloak import KeycloakOAuth2
from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.backends.saml import SAMLAuth


class LDAPBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if 'ldap' not in username:
            return None
        return super().authenticate(request, username, password, **kwargs)


class RADIUSBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if 'radius' not in username:
            return None
        return super().authenticate(request, username, password, **kwargs)


class MigratedLDAPBackend(PrefixedUserAuthenticationMixin, LDAPBackend):
    pass


class MigratedRADIUSBackend(PrefixedUserAuthenticationMixin, RADIUSBackend):
    pass


class MigratedKeycloakOAuth2(PrefixedUserAuthenticationMixin, KeycloakOAuth2):
    pass


class MigratedSAMLAuth(PrefixedUserAuthenticationMixin, SAMLAuth):
    pass


class MigratedOpenIdConnectAuth(PrefixedUserAuthenticationMixin, OpenIdConnectAuth):
    pass
