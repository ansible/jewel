import logging

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

logger = logging.getLogger('aap.gateway.signals.user')


@receiver(user_logged_out)
def user_logged_out(sender, user, request, **kwargs):
    logger.info("user logged out: %s at %s" % (user, request.META['REMOTE_ADDR']))
    # Remove the sessions so they will be repopulated on login
    user.logout()
