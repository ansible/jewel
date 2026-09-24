"""Tests for remote object RBAC visibility workaround (AAP-91996).

Validates that users who should see team assignments and access lists for
remote objects can do so despite incomplete RoleEvaluation data caused by
missing ObjectRole.parent_reference in the public/service API path.

See user_can_view_remote_rbac_object() in aap_gateway_api.utils.rbac for
the root cause analysis and the list of checks this workaround implements.
"""

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleTeamAssignment
from django.urls import reverse

from aap_gateway_api.models import Organization, Team, User


@pytest.fixture
def publisher_org():
    return Organization.objects.create(name='Publisher_ORG')


@pytest.fixture
def publisher_team(publisher_org):
    return Team.objects.create(name='Publisher_Team', organization=publisher_org)


@pytest.fixture
def consumer_team():
    org = Organization.objects.create(name='Consumer_ORG')
    return Team.objects.create(name='Consumer_Team', organization=org)


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
        name='JT Execute Remote',
        content_type=awx_jt_content_type,
        defaults={'description': 'Execute permission on a job template'},
    )
    return rd


def _make_remote_team_assignment(jt_execute_rd, consumer_team, created_by_user):
    """Create a team assignment on a remote JT with explicit created_by.

    RoleTeamAssignment inherits ImmutableModel which blocks save() after
    creation, so we use queryset.update() to set created_by.
    """
    from ansible_base.rbac.remote import RemoteObject

    remote_jt = RemoteObject(content_type=jt_execute_rd.content_type, object_id=208)
    jt_execute_rd.give_permission(consumer_team, remote_jt)
    RoleTeamAssignment.objects.filter(team=consumer_team, role_definition=jt_execute_rd, object_id='208').update(created_by=created_by_user)
    return RoleTeamAssignment.objects.get(team=consumer_team, role_definition=jt_execute_rd, object_id='208')


# -- Fixtures for "created_by" path (org member who shared access) --


@pytest.fixture
def publisher_user(publisher_org, publisher_team, local_authenticator):
    user = User.objects.create_user(username='publisher-aap91996', password='password')
    RoleDefinition.objects.get(name='Organization Member').give_permission(user, publisher_org)
    RoleDefinition.objects.get(name='Team Member').give_permission(user, publisher_team)
    return user


@pytest.fixture
def publisher_api_client(publisher_user, local_authenticator):
    from rest_framework.test import APIClient

    client = APIClient()
    client.login(username='publisher-aap91996', password='password')
    yield client
    client.logout()


@pytest.fixture
def remote_team_assignment(jt_execute_rd, consumer_team, publisher_user):
    return _make_remote_team_assignment(jt_execute_rd, consumer_team, publisher_user)


# -- Fixtures for org-scoped role path (org admin) --


@pytest.fixture
def org_admin_user(publisher_org, local_authenticator):
    user = User.objects.create_user(username='org-admin-aap91996', password='password')
    RoleDefinition.objects.get(name='Organization Admin').give_permission(user, publisher_org)
    return user


@pytest.fixture
def org_admin_api_client(org_admin_user, local_authenticator):
    from rest_framework.test import APIClient

    client = APIClient()
    client.login(username='org-admin-aap91996', password='password')
    yield client
    client.logout()


@pytest.fixture
def remote_team_assignment_not_by_admin(jt_execute_rd, consumer_team, publisher_user):
    """Assignment created by a non-admin user — org admin should still see it
    via the org-scoped role check."""
    return _make_remote_team_assignment(jt_execute_rd, consumer_team, publisher_user)


@pytest.mark.django_db
class TestCreatorVisibility:
    """created_by workaround: org member who shared access sees their assignment."""

    def test_publisher_sees_team_assignment_after_sharing(self, publisher_api_client, remote_team_assignment):
        url = get_relative_url('roleteamassignment-list')
        response = publisher_api_client.get(url, {'object_id': 208, 'content_type__model': 'jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert remote_team_assignment.id in ids

    def test_publisher_can_open_team_access_list(self, publisher_api_client, remote_team_assignment):
        url = reverse('role-team-access', kwargs={'pk': 208, 'model_name': 'awx.jobtemplate'})
        response = publisher_api_client.get(url)

        assert response.status_code == 200
        team_names = [team['name'] for team in response.data['results']]
        assert 'Consumer_Team' in team_names


@pytest.mark.django_db
class TestOrgScopedRoleVisibility:
    """Org admin sees assignments via org-scoped role permissions check."""

    def test_org_admin_sees_team_assignment(self, org_admin_api_client, remote_team_assignment_not_by_admin):
        url = get_relative_url('roleteamassignment-list')
        response = org_admin_api_client.get(url, {'object_id': 208, 'content_type__model': 'jobtemplate'})

        assert response.status_code == 200
        ids = [r['id'] for r in response.data['results']]
        assert remote_team_assignment_not_by_admin.id in ids

    def test_org_admin_can_open_team_access_list(self, org_admin_api_client, remote_team_assignment_not_by_admin):
        url = reverse('role-team-access', kwargs={'pk': 208, 'model_name': 'awx.jobtemplate'})
        response = org_admin_api_client.get(url)

        assert response.status_code == 200
        team_names = [team['name'] for team in response.data['results']]
        assert 'Consumer_Team' in team_names


@pytest.mark.django_db
class TestUnrelatedUserDenied:
    """Users without any relationship to the object are denied."""

    def test_unrelated_user_cannot_see_assignment(self, user_api_client, remote_team_assignment):
        url = get_relative_url('roleteamassignment-list')
        response = user_api_client.get(url, {'object_id': 208, 'content_type__api_slug': 'awx.jobtemplate'})

        assert response.status_code == 200
        assert remote_team_assignment.id not in [r['id'] for r in response.data['results']]

    def test_unrelated_user_gets_404_on_team_access(self, user_api_client, remote_team_assignment):
        url = reverse('role-team-access', kwargs={'pk': 208, 'model_name': 'awx.jobtemplate'})
        response = user_api_client.get(url)

        assert response.status_code == 404
