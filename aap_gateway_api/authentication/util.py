import logging

from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger('aap.gateway.authentication.util')


def load_social_auth_settings():
    logger.debug("Loading gateway social auth settings")
    return {"SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL": get_preference_value('social_auth', 'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL', encrypted=False)}
