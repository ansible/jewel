import logging

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

logger = logging.getLogger('aap.gateway.signals.user')


@receiver(user_logged_out)
def user_logged_out(sender, user, request, **kwargs):
    logger.info(f"User logged out: {user} at {request.META.get('REMOTE_ADDR', '<no remote address>')}")
    # Remove the sessions so they will be repopulated on login
    user.logout()
