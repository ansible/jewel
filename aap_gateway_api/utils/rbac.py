import functools

SYSTEM_AUDITOR_ROLE_NAME = 'System Auditor'
SYSTEM_AUDITOR_ROLE_DEFAULTS = {
    'description': 'Migrated singleton role giving read permission to everything',
    'managed': True,
}


@functools.cache
def get_system_auditor_role():
    from ansible_base.rbac.models import RoleDefinition

    system_auditor_role, _created = RoleDefinition.objects.get_or_create(
        name=SYSTEM_AUDITOR_ROLE_NAME,
        defaults=SYSTEM_AUDITOR_ROLE_DEFAULTS,
    )
    return system_auditor_role


def set_system_auditor_permissions():
    from ansible_base.rbac.models import DABPermission

    system_auditor = get_system_auditor_role()
    system_auditor.permissions.add(*list(DABPermission.objects.filter(codename__startswith='view')))
