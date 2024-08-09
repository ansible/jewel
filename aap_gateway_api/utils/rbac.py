import functools

from ansible_base.rbac.models import RoleUserAssignment
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from aap_gateway_api.models import User


@functools.cache
def get_platform_auditor_role():
    from ansible_base.rbac.models import RoleDefinition

    return RoleDefinition.objects.managed.platform_auditor


@receiver(post_save, sender=RoleUserAssignment)
@receiver(post_delete, sender=RoleUserAssignment)
def invalidate_jwt_cache_on_role_change(sender, instance, **kwargs):
    """
    Invalidate the JWT cache when a user's role assignment changes.
    This function is called when a role is assigned to or removed from a user.
    """
    from aap_gateway_api.utils.jwt_cache import invalidate_cached_jwt

    user = User.objects.filter(pk=instance.user_id).first()
    invalidate_cached_jwt(user)
