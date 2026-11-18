from aap_gateway_api.models import DomainDefinition, Organization, Team
from aap_gateway_api.services.domains import get_effective_domains


def test_domains_include_organization_for_team_only_membership(user):
    organization = Organization.objects.create(name='Team membership organization')
    team = Team.objects.create(name='Team membership team', organization=organization)
    team.add_member(user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[{'name': 'Organization domain', 'labels': []}],
    )

    assert get_effective_domains(user) == [{'name': 'Organization domain', 'labels': []}]


def test_domains_apply_precedence_across_multiple_organizations_and_teams(user):
    first_organization = Organization.objects.create(name='First domain organization')
    second_organization = Organization.objects.create(name='Second domain organization')
    first_team = Team.objects.create(name='First domain team', organization=first_organization)
    second_team = Team.objects.create(name='Second domain team', organization=second_organization)
    first_team.add_member(user)
    second_team.add_member(user)

    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=first_organization,
        domains=[{'name': 'Shared', 'labels': [{'name': 'first-org'}]}],
    )
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=second_organization,
        domains=[{'name': 'Shared', 'labels': [{'name': 'second-org'}]}],
    )
    DomainDefinition.objects.create(
        scope=DomainDefinition.TEAM,
        team=first_team,
        domains=[{'name': 'Shared', 'labels': [{'name': 'first-team'}]}],
    )
    DomainDefinition.objects.create(
        scope=DomainDefinition.TEAM,
        team=second_team,
        domains=[{'name': 'Shared', 'labels': [{'name': 'second-team'}]}],
    )

    assert get_effective_domains(user) == [{'name': 'Shared', 'labels': [{'name': 'second-team'}]}]


def test_user_domains_override_inherited_domains_without_mutating_stored_scopes(user):
    organization = Organization.objects.create(name='User override organization')
    team = Team.objects.create(name='User override team', organization=organization)
    team.add_member(user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[{'name': 'Shared', 'labels': [{'name': 'organization'}]}],
    )
    DomainDefinition.objects.create(
        scope=DomainDefinition.TEAM,
        team=team,
        domains=[{'name': 'Shared', 'labels': [{'name': 'team'}]}],
    )

    user_domains = [{'name': 'Shared', 'labels': [{'name': 'user'}]}]

    assert get_effective_domains(user, user_domains) == user_domains
    assert DomainDefinition.objects.get(scope=DomainDefinition.ORGANIZATION, organization=organization).domains == [
        {'name': 'Shared', 'labels': [{'name': 'organization'}]}
    ]
    assert DomainDefinition.objects.get(scope=DomainDefinition.TEAM, team=team).domains == [{'name': 'Shared', 'labels': [{'name': 'team'}]}]


def test_invalid_stored_domain_entries_are_ignored(user):
    organization = Organization.objects.create(name='Invalid domain organization')
    organization.add_member(user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[
            {'name': 'Valid', 'labels': []},
            {'name': '', 'labels': []},
            'not-a-domain',
            {'labels': []},
        ],
    )

    assert get_effective_domains(user) == [{'name': 'Valid', 'labels': []}]
