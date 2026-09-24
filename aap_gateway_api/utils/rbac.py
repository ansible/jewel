import functools

from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac import permission_registry
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import DABContentType, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.policies import can_view_all_users
from ansible_base.rbac.remote import RemoteObject
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


def get_remote_object_filter_from_request(request):
    """Extract (object_id, DABContentType) when the request targets a single remote object.

    Used by assignment list views to determine if the remote-object visibility
    bypass should apply.  Returns (None, None) when the request is unfiltered
    or targets a local content type.
    """
    object_id = request.query_params.get('object_id')
    if not object_id:
        return None, None

    ct_qs = DABContentType.objects.all()
    api_slug = request.query_params.get('content_type__api_slug')
    model = request.query_params.get('content_type__model')
    service = request.query_params.get('content_type__service')

    if api_slug:
        content_type = ct_qs.filter(api_slug=api_slug).first()
    elif model and service:
        content_type = ct_qs.filter(model=model, service=service).first()
    elif model:
        content_type = ct_qs.filter(model=model).first()
    else:
        return str(object_id), None

    if content_type and content_type.is_remote:
        return str(object_id), content_type
    return None, None


def user_can_view_remote_rbac_object(user, content_type, object_id) -> bool:
    """Whether *user* may list assignments / access lists for a remote object.

    WORKAROUND for incomplete RoleEvaluation data on remote objects (AAP-91996).

    Root cause
    ----------
    DAB's ``visible_items`` and ``has_obj_perm`` rely on ``RoleEvaluation``
    rows, which are computed from ``ObjectRole.parent_reference``.  For remote
    objects (e.g. AWX job templates) created through the public or service API,
    ``parent_reference`` is never populated because neither path provides the
    parent organization.  Without it, org-level role evaluations cannot
    propagate to child objects, so ``visible_items`` hides assignments the
    user should legitimately see.

    The proper long-term fix is to populate ``parent_reference`` on
    ``ObjectRole`` for remote objects — either by extending the service API
    protocol to include the parent, or by having Gateway resolve the parent
    org at assignment creation time.  That requires cross-service changes.

    This helper is a gateway-side workaround that re-derives visibility from
    data already available locally, scoped to a single remote object per
    request to avoid over-broad exposure.

    Checks (in order)
    -----------------
    1. Superuser / platform auditor / org admin with ORG_ADMINS_CAN_SEE_ALL_USERS
    2. Local ``has_obj_perm`` — works when RoleEvaluation data happens to exist
    3. Direct ``RoleUserAssignment`` on this object
    4. Org-scoped role whose permissions include this remote content type
       (mirrors what ``expected_direct_permissions`` would produce if
       ``parent_reference`` were set)
    5. User created an assignment on this object (``created_by``) — covers the
       PDF scenario where the sharer has no org admin role.  ``created_by`` is
       an audit field; using it for authorization is not ideal but is the only
       signal available without org resolution for the remote object.
    """
    if get_setting('ANSIBLE_BASE_ENFORCE_REMOTE_OBJECT_PERMISSIONS', True):
        return False

    if not content_type or not content_type.is_remote:
        return False

    # (1) Privileged users
    if can_view_all_users(user) or has_super_permission(user, 'view'):
        return True

    object_id_str = str(object_id)

    # (2) Local evaluation — works when RoleEvaluation rows exist
    remote_obj = RemoteObject(content_type=content_type, object_id=object_id)
    try:
        if user.has_obj_perm(remote_obj, 'view'):
            return True
    except RuntimeError:
        pass

    # (3) Direct object-level user assignment
    if RoleUserAssignment.objects.filter(user=user, content_type=content_type, object_id=object_id_str).exists():
        return True

    # (4) Org-scoped role with permissions covering this content type.
    # This compensates for missing parent_reference: if the user holds an org
    # role that would grant child-object evaluations (e.g. Organization Admin
    # → JobTemplate view), allow visibility.
    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)
    org_ct = DABContentType.objects.get_for_model(org_cls)
    org_assignments = (
        RoleUserAssignment.objects.filter(user=user, content_type=org_ct).select_related('role_definition').prefetch_related('role_definition__permissions')
    )
    for assignment in org_assignments:
        if assignment.role_definition.permissions.filter(content_type_id=content_type.id).exists():
            return True

    # (5) User created an assignment on this object.
    # When a user shares team/user access on a remote JT, they are recorded as
    # created_by on the assignment.  Without org resolution we cannot determine
    # whether the user "owns" the object through org membership, so we fall
    # back to this signal.  This is the minimum needed to cover the PDF
    # scenario from AAP-91996 where the sharer sees an empty Team Access UI.
    assignment_models = (RoleTeamAssignment, RoleUserAssignment)
    for model in assignment_models:
        if model.objects.filter(content_type=content_type, object_id=object_id_str, created_by=user).exists():
            return True

    return False


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
