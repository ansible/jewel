from collections import OrderedDict

from ansible_base.rbac.models import ObjectRole
from django.db.models import IntegerField
from django.db.models.functions import Cast

from aap_gateway_api.models import DomainDefinition, Organization, Team


def _merge_domains(result, definitions, scope, scope_id, scope_name):
    """Merge definitions in precedence order; later scopes replace same-name domains."""
    for domains in definitions:
        for domain in domains or []:
            if isinstance(domain, dict) and isinstance(domain.get('name'), str) and domain['name']:
                result[domain['name']] = {
                    **domain,
                    'scope': scope,
                    'scopeId': scope_id,
                    'scopeName': scope_name,
                }


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

    organization_definitions = DomainDefinition.objects.filter(organization__in=organizations).select_related('organization').order_by('organization_id')
    for definition in organization_definitions:
        _merge_domains(
            resolved,
            [definition.domains],
            DomainDefinition.ORGANIZATION,
            definition.organization_id,
            definition.organization.name,
        )

    team_definitions = DomainDefinition.objects.filter(team__in=teams).select_related('team').order_by('team_id')
    for definition in team_definitions:
        _merge_domains(resolved, [definition.domains], DomainDefinition.TEAM, definition.team_id, definition.team.name)

    if user_domains is None:
        user_definition = DomainDefinition.objects.filter(user=user).first()
        user_domains = user_definition.domains if user_definition else []
    _merge_domains(resolved, [user_domains], DomainDefinition.USER, user.id, user.username)
    return list(resolved.values())
