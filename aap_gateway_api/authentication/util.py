import logging

from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger('aap.gateway.authentication.util')


def load_social_auth_settings():
    logger.info("Loading Gateway social auth settings")
    return {"SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL": get_preference_value('social_auth', 'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL', encrypted=False)}


def get_login_redirect_override():
    return get_preference_value(section="local_login", name="LOGIN_REDIRECT_OVERRIDE", encrypted=False)
