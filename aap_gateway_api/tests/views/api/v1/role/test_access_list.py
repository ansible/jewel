import pytest
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
from django.urls import reverse

from aap_gateway_api.models import Organization, Team, User

# Test file is analog to DAB tests
# test_app/tests/rbac/api/test_access_lists.py
# but the URLs are re-included in Gateway, so this can catch some bugs


@pytest.fixture
def org_inv_admin():
    "Org role with external permissions"
    ct_id = DABContentType.objects.order_by('-id').first().id
    inv_ct, _ = DABContentType.objects.get_or_create(
        api_slug='awx.inventory', defaults={'app_label': 'main', 'model': 'inventory', 'service': 'awx', 'id': ct_id + 1}
    )
    org_ct = DABContentType.objects.get_for_model(Organization)
    perms = []
    for codename in ('change_inventory', 'delete_inventory', 'view_inventory'):
        p, _ = DABPermission.objects.get_or_create(codename=codename, content_type=inv_ct, api_slug=f'awx.{codename}')
        perms.append(p)
    perms.append(DABPermission.objects.get(codename='view_organization'))
    rd, _ = RoleDefinition.objects.get_or_create(name='inventory admin', content_type=org_ct)
    rd.permissions.set(perms)
    return rd


@pytest.mark.django_db
def test_user_access_list(admin_api_client, organization, org_inv_admin):
    url = reverse('role-user-access', kwargs={'pk': organization.pk, 'model_name': 'shared.organization'})

    u1 = User.objects.create(username='org-admin-access')
    RoleDefinition.objects.managed.org_admin.give_permission(u1, organization)

    u2 = User.objects.create(username='org-res-access')
    org_inv_admin.give_permission(u2, organization)

    u3 = User.objects.create(username='team-via-access')
    team = Team.objects.create(name='proxy-team', organization=organization)
    org_inv_admin.give_permission(team, organization)
    RoleDefinition.objects.managed.team_member.give_permission(u3, team)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_data = {}
    for user_detail in response.data['results']:
        user_data[user_detail['username']] = user_detail['object_role_assignments']
        assert 'related' in user_detail
        assert 'details' in user_detail['related']
        # Gets coverage for URLs being included correctly
        detail_url = user_detail['related']['details']
        assert detail_url.startswith('/api/gateway/')
        detail_resp = admin_api_client.get(detail_url)
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(user_detail['object_role_assignments'])

    assert u1.username in user_data
    assert len(user_data[u1.username]) == 1
    assert user_data[u1.username][0]['type'] == 'direct'

    assert u2.username in user_data
    assert len(user_data[u2.username]) == 1
    assert user_data[u2.username][0]['type'] == 'direct'

    assert u3.username in user_data
    assert len(user_data[u3.username]) == 1
    assert user_data[u3.username][0]['type'] == 'team'


@pytest.mark.django_db
def test_team_access_list(admin_api_client, org_inv_admin, organization):
    url = reverse('role-team-access', kwargs={'pk': organization.pk, 'model_name': 'shared.organization'})

    team = Team.objects.create(name='org-access', organization=organization)
    org_inv_admin.give_permission(team, organization)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    team_data = {}
    for team_detail in response.data['results']:
        team_data[team_detail['name']] = team_detail['object_role_assignments']

        assert 'related' in team_detail
        assert 'details' in team_detail['related']
        detail_url = team_detail['related']['details']
        assert detail_url.startswith('/api/gateway/')
        detail_resp = admin_api_client.get(detail_url)
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(team_detail['object_role_assignments'])

    assert team.name in team_data
    assert len(team_data[team.name]) == 1
    assert team_data[team.name][0]['type'] == 'direct'
