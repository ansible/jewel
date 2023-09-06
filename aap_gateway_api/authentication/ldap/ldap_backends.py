import logging
from collections import OrderedDict

import ldap
from django_auth_ldap.backend import LDAPBackend
from django_auth_ldap.backend import LDAPSettings as BaseLDAPSettings
from django_auth_ldap.config import LDAPSearch

from aap_gateway_api.authentication.backends import authentication_backends
from aap_gateway_api.models import Authenticator

logger = logging.getLogger('aap.gateway.authentication.ldap')


def build_ldap_authenticators():
    ldap_authenticators = Authenticator.objects.filter(type='l')
    for authenticator in ldap_authenticators:
        create_or_update_adapter(authenticator)


def create_or_update_adapter(authenticator):
    new_settings = LDAPSettings(defaults=authenticator.configuration)
    authenticator_id = f"{authenticator.id}"
    if authenticator_id not in authentication_backends:
        logger.debug(f"Creating LDAP adapter for {authenticator.name}")
        # Build the new adapter
        ldap_class = BaseLDAPBackend(authenticator=authenticator, settings=new_settings)

        # Register the new class with our auth class
        authentication_backends[authenticator_id] = ldap_class

    elif new_settings != authentication_backends[authenticator_id].settings:
        logger.debug(f"Updating LDAP adapter {authenticator.name}")
        authentication_backends[authenticator_id].settings = new_settings
        authentication_backends[authenticator_id].authenticator = authenticator
    else:
        logger.debug(f"No updated needed for LDAP adapter {authenticator.name}")


class LDAPSettings(BaseLDAPSettings):
    defaults = dict(list(BaseLDAPSettings.defaults.items()) + list({'ORGANIZATION_MAP': {}, 'TEAM_MAP': {}, 'GROUP_TYPE_PARAMS': {}}.items()))

    def __init__(self, prefix='AUTH_LDAP_', defaults={}):
        super(LDAPSettings, self).__init__(prefix, defaults)

        # TODO: move this into a serializer or something
        # Make sure connections options are legit
        if getattr(self, 'CONNECTION_OPTIONS'):
            valid_options = dict([(v, k) for k, v in ldap.OPT_NAMES_DICT.items()])
            internal_data = {}
            for opt_name, opt_value in getattr(self, 'CONNECTION_OPTIONS').items():
                internal_data[valid_options[opt_name]] = opt_value
            setattr(self, 'CONNECTION_OPTIONS', internal_data)

        # If a DB-backed setting is specified that wipes out the
        # OPT_NETWORK_TIMEOUT, fall back to a sane default
        if ldap.OPT_NETWORK_TIMEOUT not in getattr(self, 'CONNECTION_OPTIONS', {}):
            options = getattr(self, 'CONNECTION_OPTIONS', {})
            options[ldap.OPT_NETWORK_TIMEOUT] = 30
            self.CONNECTION_OPTIONS = options

        # when specifying `.set_option()` calls for TLS in python-ldap, the
        # *order* in which you invoke them *matters*, particularly in Python3,
        # where dictionary insertion order is persisted
        #
        # specifically, it is *critical* that `ldap.OPT_X_TLS_NEWCTX` be set *last*
        # this manual sorting puts `OPT_X_TLS_NEWCTX` *after* other TLS-related
        # options
        #
        # see: https://github.com/python-ldap/python-ldap/issues/55
        newctx_option = self.CONNECTION_OPTIONS.pop(ldap.OPT_X_TLS_NEWCTX, None)
        self.CONNECTION_OPTIONS = OrderedDict(self.CONNECTION_OPTIONS)
        if newctx_option is not None:
            self.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] = newctx_option

        # TODO: Move these to somewhere they are processing on setting
        # Sanitize two LDAP fields
        for field in ['GROUP_SEARCH', 'USER_SEARCH']:
            data = getattr(self, field)
            if data:
                if len(data) == 0:
                    setattr(self, field, None)
                else:
                    setattr(self, field, LDAPSearch(data[0], data[1], data[2]))


class BaseLDAPBackend(LDAPBackend):
    authenticator = None
    settings = None

    def __init__(self, authenticator=None, settings=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.authenticator = authenticator
        self.settings = settings

    def authenticate(self, request, username, password):
        if not self.authenticator.enabled:
            logger.debug(f"LDAP authenticator {self.authenticator.name} is disabled, skipping")
            return None

        configuration_errors = []
        if not self.settings.SERVER_URI:
            configuration_errors.append("Server URI must be a valid URL")

        # for setting_name, type_ in [('GROUP_SEARCH', 'LDAPSearch'), ('GROUP_TYPE', 'LDAPGroupType')]:
        #    if getattr(self.settings, setting_name) is None:
        #        configuration_errors.append("{} must be an {} instance.".format(setting_name, type_))

        if configuration_errors:
            logger.debug(f"LDAP authenticator {self.authenticator.name} can not be used due to configuration errors:\n{','.join(configuration_errors)}")
            return None

        if self.settings.START_TLS and ldap.OPT_X_TLS_REQUIRE_CERT in self.settings.CONNECTION_OPTIONS:
            # with python-ldap, if you want to set connection-specific TLS
            # parameters, you must also specify OPT_X_TLS_NEWCTX = 0
            # see: https://stackoverflow.com/a/29722445
            # see: https://stackoverflow.com/a/38136255
            self.settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] = 0

        try:
            ldap_user = super().authenticate(request, username, password)
            # If we have an LDAP user and that user we found has an ldap_user internal object and that object has a bound connection
            # Then we can try and force an unbind to close the sticky connection
            if ldap_user and ldap_user.ldap_user and ldap_user.ldap_user._connection_bound:
                logger.debug(f"Forcing LDAP connection to close for {self.authenticator.name}")
                try:
                    ldap_user.ldap_user._connection.unbind_s()
                    ldap_user.ldap_user._connection_bound = False
                except Exception:
                    logger.exception(f"Got unexpected LDAP exception when forcing LDAP disconnect for user {ldap_user}, login will still proceed")
            if ldap_user is None:
                logger.debug(f"User {username} could not be authenticated by LDAP {self.authenticator.name}")
            return ldap_user
        except Exception:
            logger.exception(f"Encountered an error authenticating to LDAP {self.authenticator.name}")
            return None
