import functools


@functools.cache
def get_platform_auditor_role():
    from ansible_base.rbac.models import RoleDefinition

    return RoleDefinition.objects.managed.platform_auditor
