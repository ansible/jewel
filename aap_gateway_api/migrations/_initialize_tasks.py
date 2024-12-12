import logging

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


def create_default_service_types(apps, schema_editor):
    """
    Create the expected default service types to seed DB.
    """
    default_service_types = [
        {
            "name": "gateway",
            "ping_url": "/api/gateway/v1/ping/",
            "login_path": None,
            "logout_path": None,
            "service_index_path": "",
        },
        {
            "name": "controller",
            "ping_url": "/api/v2/ping/",
            "login_path": "/login/",
            "logout_path": "/logout/",
            "service_index_path": "/v2/service-index/",
        },
        {
            "name": "hub",
            "ping_url": "/pulp/api/v3/status/",
            "login_path": "/auth/login",
            "logout_path": "/auth/logout",
            "service_index_path": "/service-index/",
        },
        {
            "name": "eda",
            "ping_url": "/api/eda/v1/status/",
            "login_path": "/v1/auth/session/login/",
            "logout_path": "/v1/auth/session/logout/",
            "service_index_path": "/v1/service-index/",
        },
    ]

    ServiceType = apps.get_model('aap_gateway_api.ServiceType')
    User = apps.get_model(settings.AUTH_USER_MODEL)
    system_user = User.all_objects.filter(username=settings.SYSTEM_USERNAME).first()
    for data in default_service_types:
        st = ServiceType(**data)
        st.created_by = system_user
        st.modified_by = system_user
        st.save()


def migrate_service_types(apps, schema_editor):
    ServiceCluster = apps.get_model('aap_gateway_api.ServiceCluster')
    ServiceType = apps.get_model('aap_gateway_api.ServiceType')
    for sc in ServiceCluster.objects.all():
        st = ServiceType.objects.filter(name=sc.service_type_name).first()
        sc.service_type = st
        sc.save()
