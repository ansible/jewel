import logging

from ansible_base.lib.utils.requests import get_remote_host
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from aap_gateway_api.utils.jwt_cache import JWTSessionCache

logger = logging.getLogger('aap.gateway.signals.user')


@receiver(user_logged_out)
def user_logged_out(sender, user, request, **kwargs):
    if user:
        JWTSessionCache.remove(user.pk)
        logger.info(f"User logged out: {user} at {get_remote_host(request)}")
        # Remove the sessions so they will be repopulated on login
        user.logout()
