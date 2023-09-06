import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from aap_gateway_api.models import Authenticator

logger = logging.getLogger('aap.gateway.signals.authenticator')


@receiver(post_save, sender=Authenticator)
def authenticator_changed(sender, instance, **kwargs):
    logger.info(f"Adjusting for authenticator {instance.type}/{instance.name} save")
    if instance.type == 'l':
        from aap_gateway_api.authentication.ldap.ldap_backends import create_or_update_adapter

        create_or_update_adapter(instance)
    else:
        logger.error(f"Did not know how to adjust authenticator {instance.type}/{instance.name}")
