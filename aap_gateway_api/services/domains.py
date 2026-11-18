from collections import OrderedDict

from ansible_base.rbac.models import ObjectRole
from django.db.models import IntegerField
from django.db.models.functions import Cast

from aap_gateway_api.models import DomainDefinition, Organization, Team


def _merge_domains(result, definitions):
    """Merge definitions in precedence order; later scopes replace same-name domains."""
    for definition in definitions:
        for domain in definition or []:
            if isinstance(domain, dict) and isinstance(domain.get('name'), str):
                result[domain['name']] = domain


def get_effective_domains(user, user_domains=None):
    """Resolve organization -> team -> user domains for an authenticated user."""
    resolved = OrderedDict()
    organization_ids = ObjectRole.objects.filter(
        users=user.id, role_definition__name__in=(Organization.member_rd_name, Organization.admin_rd_name)
    ).values_list(Cast('object_id', output_field=IntegerField()), flat=True)
    team_ids = ObjectRole.objects.filter(users=user.id, role_definition__name__in=(Team.member_rd_name, Team.admin_rd_name)).values_list(
        Cast('object_id', output_field=IntegerField()), flat=True
    )
    teams = Team.objects.filter(id__in=team_ids)
    organization_ids = set(organization_ids).union(teams.values_list('organization_id', flat=True))
    organizations = Organization.objects.filter(id__in=organization_ids)

    _merge_domains(resolved, DomainDefinition.objects.filter(organization__in=organizations).order_by('organization_id').values_list('domains', flat=True))
    _merge_domains(resolved, DomainDefinition.objects.filter(team__in=teams).order_by('team_id').values_list('domains', flat=True))
    _merge_domains(resolved, [user_domains] if user_domains is not None else DomainDefinition.objects.filter(user=user).values_list('domains', flat=True))
    return list(resolved.values())
