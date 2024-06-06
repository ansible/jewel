import logging

from ansible_base.lib.utils.models import get_system_user
from django.apps import apps as global_apps

logger = logging.getLogger('aap.gateway.signals.preloaded_data')


def create_preload_data(**kwargs) -> None:
    """
    Run any function in this file whose name starts with 'create_'
    All functions in this code should take no arguments and be idempotent
    If they fail, an exception (of any type) should be raised
    If an exception is raised the message "Failed to <function name replace _ with ' '>" is outputted in the logs
    """

    # Verbosity comes from the signal see https://docs.djangoproject.com/en/5.0/ref/signals/#post-migrate
    verbosity = kwargs.get('verbosity', 1)

    # Plan comes from the signal as well.
    # If this got called outside of a signal or presumably from a flush it may not exist
    if 'plan' not in kwargs:
        # If we are are being called via a flush instead of a migrate then we can just return
        return

    for migration, rolled_back in kwargs['plan']:
        if rolled_back:
            if verbosity > 0:
                logger.debug(f"We are rolling back migration {migration}, no need to create objects")
            return

    if verbosity > 0:
        logger.info("Building preloaded data")

    for function in [create_default_organization, set_system_user_managed_flag]:
        name = function.__name__
        try:
            if verbosity > 1:
                logger.info(f"Running {name}")
            created = function()
            if verbosity > 0 and created:
                logger.debug(f"Created {' '.join(name.split('_')[1:])}")
        except Exception as e:
            if verbosity in [0, 1]:
                logger.error(f"Failed to {name.replace('_', ' ')} {e}")
            elif verbosity > 1:
                logger.exception(f"Failed to {name.replace('_', ' ')}")


def create_default_organization() -> bool:
    Organization = global_apps.get_model('aap_gateway_api', 'Organization')
    _org, created = Organization.objects.get_or_create(
        name='Default', defaults={'managed': True, 'description': 'The default organization for Ansible Automation Platform'}
    )
    return created


def set_system_user_managed_flag() -> None:
    system_user = get_system_user()
    system_user.managed = True
    system_user.save()
