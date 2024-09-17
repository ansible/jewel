from django.conf import settings
from django.utils import timezone
from django.apps import apps as global_apps

from ansible_base.rbac.management import create_dab_permissions


def create_system_user(apps, schema_editor):
    """
    Create the system user using the username in settings.
    The user is self-referential in its created_by and modified_by fields.
    It is inactive, only used for attributing internal changes to the system.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)

    system_username = settings.SYSTEM_USERNAME
    if not User.objects.filter(username=system_username).exists():
        now = timezone.now()
        system_user = User.objects.create(username=system_username, is_active=False, created=now, modified=now)
        system_user.created_by = system_user
        system_user.modified_by = system_user
        system_user.save()


def create_permissions_as_operation(apps, schema_editor):
    create_dab_permissions(global_apps.get_app_config("aap_gateway_api"), apps=apps)
