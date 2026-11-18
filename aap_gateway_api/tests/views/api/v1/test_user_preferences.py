from django.urls import reverse
from rest_framework.test import APIClient

from aap_gateway_api.models import DomainDefinition, Organization, Team, User


def user_preferences_url(name='domains'):
    return reverse('user-preference-detail', kwargs={'preference_name': name})


def test_user_preference_is_private_and_persistent(user):
    user_api_client = APIClient()
    user_api_client.force_authenticate(user=user)
    value = {
        'domains': [
            {'name': 'Network', 'labels': [{'name': 'network'}]},
        ],
        'activeDomains': [],
    }

    response = user_api_client.put(user_preferences_url(), {'value': value}, format='json')

    assert response.status_code == 200
    assert response.data == {'name': 'domains', 'value': {**value, 'userDomains': value['domains']}}

    response = user_api_client.get(user_preferences_url())
    assert response.status_code == 200
    assert response.data == {'name': 'domains', 'value': {**value, 'userDomains': value['domains']}}

    other_user = User.objects.create(username='other-user')
    other_client = APIClient()
    other_client.force_authenticate(user=other_user)
    response = other_client.get(user_preferences_url())
    assert response.status_code == 200
    assert response.data == {'name': 'domains', 'value': None}


def test_user_preference_requires_authentication(unauthenticated_api_client):
    response = unauthenticated_api_client.get(user_preferences_url())

    assert response.status_code == 401


def test_user_preference_rejects_invalid_domain_value(user):
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.put(user_preferences_url(), {'value': {}}, format='json')

    assert response.status_code == 400
    assert 'domains' in response.data['value']
    assert 'activeDomains' in response.data['value']

    response = client.put(
        user_preferences_url(),
        {'value': {'domains': ['not-a-domain'], 'activeDomains': []}},
        format='json',
    )
    assert response.status_code == 400


def test_domains_inherit_organization_then_team_then_user(user):
    organization = Organization.objects.create(name='Domain inheritance org')
    team = Team.objects.create(name='Domain inheritance team', organization=organization)
    organization.add_member(user)
    team.add_member(user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[{'name': 'Shared', 'labels': [{'name': 'org'}]}, {'name': 'Org only', 'labels': []}],
    )
    DomainDefinition.objects.create(
        scope=DomainDefinition.TEAM,
        team=team,
        domains=[{'name': 'Shared', 'labels': [{'name': 'team'}]}, {'name': 'Team only', 'labels': []}],
    )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(user_preferences_url())

    assert response.status_code == 200
    assert response.data['value']['domains'] == [
        {'name': 'Shared', 'labels': [{'name': 'team'}]},
        {'name': 'Org only', 'labels': []},
        {'name': 'Team only', 'labels': []},
    ]
    assert response.data['value']['activeDomains'] == []
    assert response.data['value']['userDomains'] == []


def test_user_domains_override_inherited_domain_without_changing_active_selection(user):
    organization = Organization.objects.create(name='Domain override org')
    organization.add_member(user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[{'name': 'Shared', 'labels': [{'name': 'org'}]}],
    )
    client = APIClient()
    client.force_authenticate(user=user)
    value = {
        'domains': [{'name': 'Shared', 'labels': [{'name': 'user'}]}, {'name': 'User only', 'labels': []}],
        'activeDomains': [{'name': 'Shared', 'labels': [{'name': 'user'}]}],
    }

    response = client.put(user_preferences_url(), {'value': value}, format='json')

    assert response.status_code == 200
    assert response.data['value'] == {**value, 'userDomains': value['domains']}
    definition = DomainDefinition.objects.get(scope=DomainDefinition.USER, user=user)
    assert definition.domains == value['domains']


def test_organization_domains_can_be_managed_by_an_organization_admin(user, admin_user):
    organization = Organization.objects.create(name='Domain API org')
    organization.add_admin(admin_user)
    client = APIClient()
    client.force_authenticate(user=admin_user)

    response = client.put(
        reverse('organization-domain-definition', kwargs={'pk': organization.pk}),
        {'domains': [{'name': 'Org domain', 'labels': []}]},
        format='json',
    )

    assert response.status_code == 200
    assert response.data == {'scope': 'organization', 'domains': [{'name': 'Org domain', 'labels': []}]}
    assert DomainDefinition.objects.get(organization=organization).domains == [{'name': 'Org domain', 'labels': []}]


def test_organization_domain_reads_are_private(user, admin_user):
    organization = Organization.objects.create(name='Private domain API org')
    organization.add_admin(admin_user)
    DomainDefinition.objects.create(
        scope=DomainDefinition.ORGANIZATION,
        organization=organization,
        domains=[{'name': 'Private org domain', 'labels': []}],
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(reverse('organization-domain-definition', kwargs={'pk': organization.pk}))

    assert response.status_code == 403


def test_deleting_user_preference_removes_user_scope(user):
    client = APIClient()
    client.force_authenticate(user=user)
    value = {'domains': [{'name': 'User domain', 'labels': []}], 'activeDomains': []}
    client.put(user_preferences_url(), {'value': value}, format='json')

    response = client.delete(user_preferences_url())

    assert response.status_code == 204
    assert not DomainDefinition.objects.filter(scope=DomainDefinition.USER, user=user).exists()
