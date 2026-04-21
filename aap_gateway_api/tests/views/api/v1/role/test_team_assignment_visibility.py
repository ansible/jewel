"""Tests for GatewayRoleTeamAssignmentViewSet.filter_queryset (AAP-70503).

Org admins with ORG_ADMINS_CAN_SEE_ALL_USERS enabled should be able to see
team role assignments on remote objects (e.g. AWX job templates), even though
the gateway's RoleEvaluation cache does not cover those objects.
"""

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleTeamAssignment

from aap_gateway_api.models import Organization, Team, User


@pytest.fixture
def org_a():
    return Organization.objects.create(name='OrgA')


@pytest.fixture
def org_b():
    return Organization.objects.create(name='OrgB')


@pytest.fixture
def team_orgb(org_b):
    return Team.objects.create(name='team-orgb', organization=org_b)


@pytest.fixture
def org_admin_user(org_a, local_authenticator):
    user = User.objects.create_user(username='org-admin', password='password')
    org_admin_rd = RoleDefinition.objects.get(name='Organization Admin')
    org_admin_rd.give_permission(user, org_a)
    return user


@pytest.fixture
def org_admin_api_client(org_admin_user, local_authenticator):
    from rest_framework.test import APIClient

    client = APIClient()
    client.login(username='org-admin', password='password')
    yield client
    client.logout()


@pytest.fixture
def awx_jt_content_type():
    defaults = {
        'id': max(DABContentType.objects.values_list('id', flat=True), default=0) + 1,
        'app_label': 'awx',
        'api_slug': 'awx.jobtemplate',
        'pk_field_type': 'integer',
    }
    ct, _ = DABContentType.objects.get_or_create(service='awx', model='jobtemplate', defaults=defaults)
    return ct


@pytest.fixture
def jt_execute_rd(awx_jt_content_type):
    rd, _ = RoleDefinition.objects.get_or_create(
        name='JT Execute',
        content_type=awx_jt_content_type,
        defaults={'description': 'Execute permission on a job template'},
    )
    return rd


@pytest.fixture
def cross_org_team_assignment(jt_execute_rd, team_orgb):
    """Create a team assignment for team-orgb on a remote JT (object_id=105).

    Uses give_permission directly to bypass the resource sync layer.
    """
    from ansible_base.rbac.remote import RemoteObject

    remote_jt = RemoteObject(content_type=jt_execute_rd.content_type, object_id=105)
    jt_execute_rd.give_permission(team_orgb, remote_jt)
    return RoleTeamAssignment.objects.get(team=team_orgb, role_definition=jt_execute_rd, object_id='105')


@pytest.mark.django_db
class TestOrgAdminTeamAssignmentVisibility:
    """AAP-70503: org admins should see cross-org team assignments on remote objects."""

    def test_org_admin_sees_assignment_with_setting_enabled(self, org_admin_api_client, cross_org_team_assignment, preference_manager):
        with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', True):
            url = get_relative_url('roleteamassignment-list')
            response = org_admin_api_client.get(url, {'object_id': 105, 'content_type__api_slug': 'awx.jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert cross_org_team_assignment.id in ids

    def test_org_admin_cannot_see_assignment_with_setting_disabled(self, org_admin_api_client, cross_org_team_assignment, preference_manager):
        with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', False):
            url = get_relative_url('roleteamassignment-list')
            response = org_admin_api_client.get(url, {'object_id': 105, 'content_type__api_slug': 'awx.jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert cross_org_team_assignment.id not in ids

    def test_superuser_always_sees_assignment(self, admin_api_client, cross_org_team_assignment):
        url = get_relative_url('roleteamassignment-list')
        response = admin_api_client.get(url, {'object_id': 105, 'content_type__api_slug': 'awx.jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert cross_org_team_assignment.id in ids

    def test_regular_user_cannot_see_assignment(self, user_api_client, cross_org_team_assignment):
        url = get_relative_url('roleteamassignment-list')
        response = user_api_client.get(url, {'object_id': 105, 'content_type__api_slug': 'awx.jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert cross_org_team_assignment.id not in ids

    def test_org_admin_sees_assignment_in_unfiltered_list(self, org_admin_api_client, cross_org_team_assignment, preference_manager):
        """The assignment should appear even without object_id filtering."""
        with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', True):
            url = get_relative_url('roleteamassignment-list')
            response = org_admin_api_client.get(url)

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert cross_org_team_assignment.id in ids

    def test_org_admin_sees_local_object_assignment_regardless_of_setting(self, org_admin_api_client, org_a, team_orgb, preference_manager):
        """Assignments on local objects (e.g. teams) should be visible
        through the normal visible_items path, independent of the setting."""
        team_orga = Team.objects.create(name='team-orga', organization=org_a)
        team_member_rd = RoleDefinition.objects.get(name='Team Member')
        team_member_rd.give_permission(team_orgb, team_orga)
        assignment = RoleTeamAssignment.objects.get(team=team_orgb, role_definition=team_member_rd, object_id=str(team_orga.id))

        with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', False):
            url = get_relative_url('roleteamassignment-list')
            response = org_admin_api_client.get(url, {'object_id': team_orga.id})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert assignment.id in ids
