import functools


@functools.cache
def get_system_auditor_role():
    from ansible_base.rbac.models import RoleDefinition

    return RoleDefinition.objects.managed.sys_auditor
