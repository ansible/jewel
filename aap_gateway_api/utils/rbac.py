import functools

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleUserAssignment
from ansible_base.rbac.policies import can_view_all_users
from django.apps import apps
from django.conf import settings
from django.db.models import QuerySet
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


def visible_teams(request_user, queryset=None) -> QuerySet:
    """Gives a queryset of teams that another user should be able to view"""
    team_cls = permission_registry.team_model

    if not getattr(request_user, "is_authenticated", False):
        return team_cls.objects.none()

    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

    if can_view_all_users(request_user):
        if queryset is not None:
            return queryset
        else:
            return team_cls.objects.all()

    # Teams belong directly to organizations via ForeignKey, so filter by visible organizations
    visible_org_ids = org_cls.access_ids_qs(request_user, 'view')
    if queryset is None:
        queryset = team_cls.objects

    queryset = queryset.filter(organization_id__in=visible_org_ids)
    return queryset.distinct()
