import logging

from ansible_base.lib.utils.models import get_system_user
from ansible_base.rbac.permission_registry import permission_registry
from django.apps import apps as global_apps

from aap_gateway_api.models import ServiceType

logger = logging.getLogger('aap.gateway.signals.preloaded_data')


def create_preload_data(**kwargs) -> None:
    """
    Run functions in a given order to create pre-loaded data
    All functions in this code should take no arguments and be idempotent
    If they fail, an exception (of any type) should be raised
    If an exception is raised the message "Failed to <function name replace _ with ' '>" is outputted in the logs
    """

    function_order = [
        set_jwt_key_pair,
        create_default_organization,
        create_managed_roles,
        set_system_user_password,
        set_system_user_managed_flag,
        add_console_service_type,
    ]

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

    for function in function_order:
        name = function.__name__
        try:
            if verbosity > 1:
                logger.info(f"Running {name}")
            created = function()
            if verbosity > 0 and created:
                action = 'Created'
                if name.startswith('set'):
                    action = 'Set'
                logger.debug(f"{action} {' '.join(name.split('_')[1:])}")
        except Exception as e:
            if verbosity in [0, 1]:
                logger.error(f"Failed to {name.replace('_', ' ')} {e}")
            elif verbosity > 1:
                logger.exception(f"Failed to {name.replace('_', ' ')}")


def set_jwt_key_pair() -> bool:
    from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

    # If the jwt_private_key is not set, we need to add one for the gateway to be usable
    if get_preference_value(section='proxy', name='jwt_private_key', encrypted=False) != '':
        return False

    from aap_gateway_api.utils.jwt_token import generate_jwt_keypair

    key_pair = generate_jwt_keypair()
    update_preference_value(section='proxy', name='jwt_private_key', value=key_pair.private, validate=True)
    # Since we are validating, this should auto-update the public key as well

    return True


def create_default_organization() -> bool:
    Organization = global_apps.get_model('aap_gateway_api', 'Organization')
    _org, created = Organization.objects.get_or_create(
        name='Default', defaults={'managed': True, 'description': 'The default organization for Ansible Automation Platform'}
    )
    return created


def create_managed_roles() -> None:
    permission_registry.create_managed_roles(global_apps)


def set_system_user_password() -> bool:
    # When the system user is created by a migration it can't call set_usable_password because is of class <__fake__.User>
    system_user = get_system_user()
    if system_user.has_usable_password:
        system_user.set_unusable_password()
        system_user.save()
        return True
    else:
        return False


def set_system_user_managed_flag() -> None:
    system_user = get_system_user()
    if system_user.managed:
        return False
    system_user.managed = True
    system_user.save()
    return True


def add_console_service_type() -> None:
    # Add console.redhat.com service type
    console_type = {
        "name": "console",
    }
    ServiceType.objects.get_or_create(**console_type)
