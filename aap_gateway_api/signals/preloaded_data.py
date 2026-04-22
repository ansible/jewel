import logging

from ansible_base.lib.utils.models import get_system_user
from ansible_base.rbac.management import create_dab_permissions
from ansible_base.rbac.permission_registry import permission_registry
from django.apps import apps as global_apps
from django.conf import settings
from flags.state import flag_enabled, get_flags

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
        toggle_install_time_flags,
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
    _org, created = Organization.objects.get_or_create(name='Default', defaults={'managed': True, 'description': 'Specifies the default organization.'})
    return created


def create_managed_roles() -> None:
    # Permissions and types must be created before creating managed roles
    create_dab_permissions(global_apps.get_app_config('dab_rbac'))
    # Create the managed=True entries of RoleDefinition model
    permission_registry.create_managed_roles(global_apps)


def set_system_user_password() -> bool:
    # When the system user is created by a migration it can't call set_usable_password because is of class <__fake__.User>
    system_user = get_system_user()
    if system_user.has_usable_password():
        system_user.set_unusable_password()
        system_user.save()
        return True
    else:
        return False


def set_system_user_managed_flag() -> bool:
    system_user = get_system_user()
    if system_user.managed:
        return False
    system_user.managed = True
    system_user.save()
    return True


def add_console_service_type() -> bool:
    if flag_enabled("FEATURE_GATEWAY_CREATE_CRC_SERVICE_TYPE_ENABLED"):
        # Add console.redhat.com service type
        _obj, created = ServiceType.objects.get_or_create(name="console")
        return created
    return False


def toggle_install_time_flags() -> None:
    """
    Apply install-time feature flag values from settings.

    Feature Flag Order Precedence:
    1. Install-time specified values take precedence over all other sources
       - Flag overrides can be defined at install time to define their initial state
       - Value is saved to the database
       - If a feature flag is set at install time, it becomes READ-ONLY and cannot be changed at runtime
    2. Runtime feature flags can only be toggled if they were NOT explicitly set at install time
       AND RUNTIME_FEATURE_FLAGS=True
    3. When the installer is rerun, install-time specified feature flag values are always applied
       - If a flag was previously toggled at runtime but is now specified at install-time,
         the install-time value takes precedence
    """
    aap_flags_model = global_apps.get_model('dab_feature_flags', 'AAPFlag')
    for flag in get_flags():
        if hasattr(settings, flag) and isinstance(getattr(settings, flag), bool):
            state = str(getattr(settings, flag))
            try:
                existing_flag = aap_flags_model.objects.get(name=flag, condition="boolean")
            except aap_flags_model.DoesNotExist:
                logger.warning(f"Feature flag {flag} not found in database. Skipping toggle. This may indicate that DAB's load_feature_flags has not run yet.")
                continue
            # Install-time specified values always take precedence over runtime changes
            logger.info(f"Applying install-time feature flag: {flag} to {state}")
            existing_flag.value = state
            existing_flag.full_clean()
            existing_flag.save()
