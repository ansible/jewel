import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleUserAssignment
from django.urls import reverse

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.tests.views.api.v1.conftest import api_get_and_assert


def associate_logged_user(teams, organizations, user):
    """
    Making memberships:
     Request user is:
     - Org 1: Team Member of Team 1 + no membership on Team 2
     - Org 2: Team Admin of Team 3 + no membership on Team 4
     - Org 3: Team Member of Team 5 + Team Admin of Team 6
     - Org 4: Org Member
     - Org 5: Org Admin
     - Org 6: No membership
    """
    teams[organizations[0]][0].add_member(user)
    teams[organizations[1]][0].add_admin(user)
    teams[organizations[2]][0].add_member(user)
    teams[organizations[2]][1].add_admin(user)
    organizations[3].add_member(user)
    organizations[4].add_admin(user)


def _visible_teams(teams, organizations, org_admins_can_see_all=True):
    """
    Based on associate_logged_user()
    When ORG_ADMINS_CAN_SEE_ALL_USERS=True (default): Org Admins can see ALL teams
    When ORG_ADMINS_CAN_SEE_ALL_USERS=False: falls through to DAB access_qs, so
      visibility comes from RBAC permissions - team member/admin see their teams,
      org member sees all teams in their org, org admin sees all teams in their org.
    """
    if org_admins_can_see_all:
        all_teams = []
        for org in organizations:
            all_teams.extend(teams[org])
        return sorted(all_teams, key=lambda t: t.id)
    else:
        visible = [
            teams[organizations[0]][0],  # Team member
            teams[organizations[1]][0],  # Team admin
            teams[organizations[2]][0],  # Team member
            teams[organizations[2]][1],  # Team admin
        ]
        visible += teams[organizations[3]]  # All teams from org where user is org member
        visible += teams[organizations[4]]  # All teams from org where user is org admin
        return visible


def _editable_teams(teams, organizations):
    """
    Base on associate_logged_user()
    Org Admins and Team Admins can edit team
    """
    return [teams[organizations[1]][0], teams[organizations[2]][1]] + teams[organizations[4]]


def test_team_list_permissions(user_api_client, user, teams, organizations):  # noqa: F811
    """
    Teams in list can see:
    - Superuser (other tests)
    - Org Admin can see ALL teams (when ORG_ADMINS_CAN_SEE_ALL_USERS=True, which is the default)
    - Admin or User of Team
    - Admin or User of Team's Org
    """
    url = get_relative_url("team-list")

    # User sees nothing by default
    api_get_and_assert(url, user_api_client, [])

    associate_logged_user(teams, organizations, user)
    expected_teams = _visible_teams(teams, organizations)
    api_get_and_assert(url, user_api_client, expected_teams, order_by="id")


def test_team_detail_permissions(user_api_client, user, teams, organizations):  # noqa: F811
    """
    Detail of team can read:
    - Superuser (other tests)
    - Org Admin can see ALL teams (when ORG_ADMINS_CAN_SEE_ALL_USERS=True, which is the default)
    - Admin or User of Team
    - Admin or User of Team's Org
    """
    visible_teams = _visible_teams(teams, organizations)

    for status in ['disassociated', 'associated']:
        for org, org_teams in teams.items():
            for org_team in org_teams:
                url = get_relative_url("team-detail", kwargs={'pk': org_team.pk})

                response = user_api_client.get(url)
                if status == 'associated' and org_team in visible_teams:
                    assert response.status_code == 200, f"Team {org_team.name} should be accessible"
                else:
                    assert response.status_code == 404, f"Team {org_team.name} should not be accessible"

        associate_logged_user(teams, organizations, user)


def test_team_create_permissions(user_api_client, user, organization, org_admin_rd, org_member_rd):
    url = get_relative_url('team-list')
    create_data = {'name': 'new-team', 'organization': organization.pk}

    # Can not see organization
    response = user_api_client.post(url, data=create_data)
    assert not user.has_obj_perm(organization, 'view')  # sanity
    assert response.status_code == 400, response.data

    # Does not have permission to create teams in organization
    org_member_rd.give_permission(user, organization)
    assert user.has_obj_perm(organization, 'view')  # sanity
    assert not user.has_obj_perm(organization, 'change')  # sanity
    response = user_api_client.post(url, data=create_data)
    assert response.status_code == 403, response.data

    # With org admin permission, the team can be created
    org_admin_rd.give_permission(user, organization)
    response = user_api_client.post(url, data=create_data)
    assert response.status_code == 201


@pytest.mark.parametrize("api_type", ["old", "new"])
def test_team_detail_associate_members(user_api_client, user, organization, team, admin_rd, member_rd, org_member_rd, api_type):
    rando = User.objects.create(username='rando')
    admin_rd.give_permission(user, team)

    if api_type == "old":
        url = get_relative_url('team-users-associate', kwargs={'pk': team.pk})
        # data to add rando as a member
        patch_data = {'instances': [rando.id]}
        # user can not add rando as a member due to not being able to view that user
        response = user_api_client.post(url, data=patch_data)
        assert not team.users.filter(id=rando.id).exists()
        assert response.status_code == 400, response.data
    else:
        url = get_relative_url('roleuserassignment-list')
        data = {'object_id': team.pk, 'user': rando.id, 'role_definition': member_rd.id}
        response = user_api_client.post(url, data=data)
        assert response.status_code == 400, response.data

    for u in (user, rando):
        org_member_rd.give_permission(u, organization)

    # user now see rando (and is admin of the team) so criteria for adding member is met
    if api_type == 'old':
        response = user_api_client.post(url, data=patch_data)
        assert response.status_code == 204
    else:
        response = user_api_client.post(url, data=data)
        assert response.status_code == 201, response.data


@pytest.mark.parametrize("api_type", ["old_api", "new_api"])
@pytest.mark.parametrize("user_type", ["admin", "member", "self-admin", "self-member"])
def test_team_detail_disassociate_members(user_api_client, user, user_type, organization, team, admin_rd, member_rd, org_member_rd, api_type):
    """Team Admin can always disassociate team member/team admin (self and other user)"""
    team.add_admin(user)

    if user_type in ['admin', 'member']:
        team_user = User.objects.create(username='rando')
    else:
        team_user = user

    if user_type in ['admin', 'self-admin']:
        team.add_admin(team_user)
        viewname = 'team-admins-disassociate'
        rd_id = admin_rd.id
    else:
        team.add_member(team_user)
        viewname = 'team-users-disassociate'
        rd_id = member_rd.id

    if api_type == "old_api":
        url = get_relative_url(viewname, kwargs={'pk': team.pk})
        patch_data = {'instances': [team_user.id]}
        response = user_api_client.post(url, data=patch_data)
    else:
        user_role = RoleUserAssignment.objects.get(object_id=team.pk, user_id=team_user.id, role_definition_id=rd_id)
        url = get_relative_url('roleuserassignment-detail', kwargs={'pk': user_role.id})
        response = user_api_client.delete(url)

    assert response.status_code == 204
    if user_type in ['admin', 'self-admin']:
        assert not team.admins.filter(id=team_user.id).exists()
    else:
        assert not team.users.filter(id=team_user.id).exists()


def test_team_update_no_roles_permissions(user_api_client, user, teams, organizations, org_member_rd):  # noqa: F811
    """Basic user can't update any team"""
    for org, org_teams in teams.items():
        # user needs to have view permission to organization in order to PUT
        for org_team in org_teams:
            url = get_relative_url("team-detail", kwargs={"pk": org_team.pk})
            changed_data = {"name": f"{org_team.name}-Changed", "description": "This is a testing team"}

            response = user_api_client.put(url, data=changed_data)

            assert response.status_code == 404, f"Team {org_team.name} should be inaccessible"


@pytest.mark.parametrize("method", ["put", "patch"])
def test_team_update_with_roles_permissions(user_api_client, user, teams, organizations, method, org_member_rd):  # noqa: F811
    """
    Team can be updated by:
    - Superuser (other tests)
    - Admin or Team
    - Admin of Team's Organization
    Team's Organization can be updated by:
    - Superuser (other tests)
    - Admin of (source Team or source Team's Organization) AND (Admin of destination Team and Admin of destination Team's Organization)
    Team can be deleted by:
    - Superuser (other tests)
    - Admin of Team
    - Admin of Team's Organization

    """
    associate_logged_user(teams, organizations, user)
    visible_teams = _visible_teams(teams, organizations)
    changeable_teams = _editable_teams(teams, organizations)

    user_api_call = getattr(user_api_client, method)

    for org, org_teams in teams.items():
        # user needs to have view permission to organization in order to PUT
        for org_team in org_teams:
            url = get_relative_url("team-detail", kwargs={"pk": org_team.pk})

            changed_data = {"name": f"{org_team.name}-Changed", "description": "This is a testing team"}

            response = user_api_call(url, data=changed_data)

            if org_team in changeable_teams:
                assert response.status_code == 200, f"Team {org_team.name} should be updatable, data:\n{response.data}"
                assert response.data["name"] == changed_data["name"]
                assert response.data["description"] == changed_data["description"]
            elif org_team in visible_teams:  # and not in changeable_teams
                assert response.status_code == 403, f"Update of Team {org_team.name} should be forbidden"
            else:
                assert response.status_code == 404, f"Team {org_team.name} should be inaccessible"


def test_team_delete_no_roles_permissions(user_api_client, user, teams, organizations):
    """Basic user can't delete any team"""
    for org, org_teams in teams.items():
        for org_team in org_teams:
            url = get_relative_url("team-detail", kwargs={"pk": org_team.pk})
            response = user_api_client.delete(url)

            assert response.status_code == 404, f"Team {org_team.name} should be inaccessible"


@pytest.mark.django_db
def test_team_delete_with_roles_permissions(user_api_client, user, teams, organizations):
    """Deleting teams has the same rules as updating"""
    associate_logged_user(teams, organizations, user)
    visible_teams = _visible_teams(teams, organizations)
    deletable_teams = _editable_teams(teams, organizations)

    for org, org_teams in teams.items():
        for org_team in org_teams:
            url = get_relative_url("team-detail", kwargs={"pk": org_team.pk})
            response = user_api_client.delete(url)

            if org_team in deletable_teams:
                assert response.status_code == 204, f"Team {org_team.name} should be deletable"
            elif org_team in visible_teams:
                assert response.status_code == 403, f"Team {org_team.name} shouldn't be deletable"
            else:
                assert response.status_code == 404, f"Team {org_team.name} should be inaccessible"


@pytest.mark.django_db
@pytest.mark.parametrize("setting_value", [True, False])
def test_team_org_admin_permissions_with_setting(user_api_client, user, teams, organizations, preference_manager, setting_value):
    """Test org admin team visibility with different ORG_ADMINS_CAN_SEE_ALL_USERS values"""
    associate_logged_user(teams, organizations, user)

    with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', setting_value):
        # Test team list visibility
        url = get_relative_url("team-list")
        response = user_api_client.get(url, {"order_by": "id"})
        assert response.status_code == 200

        expected_teams = _visible_teams(teams, organizations, org_admins_can_see_all=setting_value)
        actual_team_ids = {t['id'] for t in response.data['results']}
        expected_team_ids = {t.id for t in expected_teams}
        if setting_value:
            # When True: org admin should see all teams
            total_teams = sum(len(org_teams) for org_teams in teams.values())
            assert response.data['count'] == total_teams, f"Org Admin should see all {total_teams} teams when ORG_ADMINS_CAN_SEE_ALL_USERS=True"
            assert actual_team_ids == expected_team_ids, "Org Admin should see all teams when ORG_ADMINS_CAN_SEE_ALL_USERS=True"
        else:
            # When False: org admin should see limited teams (from their own org + teams where they're member/admin)
            assert response.data['count'] == len(expected_teams), f"Org Admin should see {len(expected_teams)} teams when ORG_ADMINS_CAN_SEE_ALL_USERS=False"
            assert actual_team_ids == expected_team_ids, "Org Admin should see limited teams when ORG_ADMINS_CAN_SEE_ALL_USERS=False"
            assert response.data['count'] < sum(len(org_teams) for org_teams in teams.values()), (
                "Org Admin should see fewer teams when ORG_ADMINS_CAN_SEE_ALL_USERS=False"
            )

        # Test detail view for teams from different organizations
        # Test a team from an organization where user is NOT org admin and NOT team member/admin
        different_org = organizations[5]  # User has no membership in org 5
        different_org_team = teams[different_org][0]
        url = get_relative_url("team-detail", kwargs={"pk": different_org_team.pk})
        response = user_api_client.get(url)

        if setting_value:
            assert response.status_code == 200, f"Org Admin should see {different_org_team.name} when ORG_ADMINS_CAN_SEE_ALL_USERS=True"
        else:
            assert response.status_code == 404, f"Org Admin should not see {different_org_team.name} when ORG_ADMINS_CAN_SEE_ALL_USERS=False"


@pytest.mark.django_db
class TestTeamOptions:
    @staticmethod
    def _assoc_role(role, user, team, organization, member_rd, admin_rd, org_member_rd, org_admin_rd):
        team_roles = [member_rd, admin_rd]
        org_roles = [org_member_rd, org_admin_rd]
        for team_role in team_roles:
            if role == team_role:
                team_role.give_permission(user, team)
            else:
                team_role.remove_permission(user, team)
        for org_role in org_roles:
            if role == org_role:
                org_role.give_permission(user, organization)
            else:
                org_role.remove_permission(user, organization)

    def test_teams_list_options_user(self, user_api_client, user, team, organization, member_rd, admin_rd, org_member_rd, org_admin_rd):
        """Only Org Admin role can create team"""
        url = get_relative_url("team-list")
        roles = [None, member_rd, admin_rd, org_member_rd, org_admin_rd]
        for role in roles:
            self._assoc_role(role, user, team, organization, member_rd, admin_rd, org_member_rd, org_admin_rd)
            role_name = role.name if role else 'No Team/Org role'

            response = user_api_client.options(url)
            assert response.status_code == 200
            post_action = response.data.get('actions', {}).get('POST', None)
            if role == org_admin_rd:
                assert post_action is not None, f"POST action should be available for {role_name}"
            else:
                assert post_action is None, f"POST action shouldn't be available for {role_name}"

    def test_teams_list_options_platform_auditor(self, user_api_client, user):
        url = get_relative_url("team-list")
        user.is_platform_auditor = True
        user.save()

        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('POST', None) is None, "POST action shouldn't be available for system auditor"

    def test_teams_list_options_superuser(self, admin_api_client, user):
        url = get_relative_url("team-list")

        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('POST', None) is not None, "POST action should be available for superuser"

    def test_team_detail_options_user(self, user_api_client, user, team, organization, member_rd, admin_rd, org_member_rd, org_admin_rd):
        """Only Team/Org Admin can change team"""
        url = get_relative_url("team-detail", kwargs={"pk": team.pk})
        roles = [None, member_rd, admin_rd, org_member_rd, org_admin_rd]
        for role in roles:
            self._assoc_role(role, user, team, organization, member_rd, admin_rd, org_member_rd, org_admin_rd)
            role_name = role.name if role else 'No Team/Org role'

            response = user_api_client.options(url)
            assert response.status_code == 200

            put_action = response.data.get('actions', {}).get('PUT', None)

            if role in [admin_rd, org_admin_rd]:
                assert put_action is not None, f"PUT action should be available for {role_name}"
            else:
                assert put_action is None, f"PUT action shouldn't be available for {role_name}"

    def test_team_detail_options_platform_auditor(self, user_api_client, user, team):
        url = get_relative_url("team-detail", kwargs={"pk": team.pk})
        user.is_platform_auditor = True
        user.save()

        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for system auditor"

    def test_team_detail_options_superuser(self, admin_api_client, user, team):
        url = get_relative_url("team-detail", kwargs={"pk": team.pk})

        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action should be available for superuser"


@pytest.mark.django_db
@pytest.mark.parametrize('org_admins_can_see_all', [True, False], ids=['see_all=True', 'see_all=False'])
def test_pure_org_member_can_see_teams_in_org(user_api_client, user, org_member_rd, preference_manager, org_admins_can_see_all):
    """Regression test for AAP-79673.

    A user who is ONLY an org member (no org admin role anywhere) should see
    teams in their organization via the team list API.  Before the fix,
    can_view_all_users() returned False for such users, so the view fell
    through to access_qs which did not grant view_team to org members.

    Parametrized on ORG_ADMINS_CAN_SEE_ALL_USERS because a pure org member
    (no org admin role) should behave identically regardless of this setting.
    """
    org = Organization.objects.create(name='OrgMember-Only Org')
    other_org = Organization.objects.create(name='Other Org')
    team_in_org = Team.objects.create(name='Visible Team', organization=org)
    hidden_team = Team.objects.create(name='Hidden Team', organization=other_org)

    org_member_rd.give_permission(user, org)

    with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', org_admins_can_see_all):
        url = get_relative_url("team-list")
        response = user_api_client.get(url)
        assert response.status_code == 200
        team_ids = {t['id'] for t in response.data['results']}
        assert team_in_org.pk in team_ids, "Org member should see teams in their org"
        assert response.data['count'] == 1, "Org member should only see teams from their own org"

        detail_url = get_relative_url("team-detail", kwargs={'pk': team_in_org.pk})
        response = user_api_client.get(detail_url)
        assert response.status_code == 200, "Org member should access team detail in their org"

        hidden_detail_url = get_relative_url("team-detail", kwargs={'pk': hidden_team.pk})
        response = user_api_client.get(hidden_detail_url)
        assert response.status_code == 404, "Org member should NOT access teams in other orgs"


@pytest.mark.django_db
def test_team_users_associate_propagates_to_role_user_access(admin_api_client, organization, team):
    """Regression test for AAP-50880.

    Users added to a team via the deprecated /api/v1/teams/N/users/associate/ endpoint
    must appear in role_user_access for objects the team has a role on.

    The endpoint must call RoleDefinition.give_permission() (creating a RoleUserAssignment),
    not the raw M2M .add() path, so that DAB's RBAC evaluation tables are populated and
    the user is visible in role_user_access with type='team'.
    """
    rando = User.objects.create(username='rando-aap50880')

    # Create a custom org-level role that CAN be assigned to teams.
    # The managed Organization Member role is blocked by ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER=False,
    # so we use a custom role following the pattern from DAB's test_access_lists.py.
    org_ct = DABContentType.objects.get_for_model(Organization)
    org_viewer_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization'],
        name='test-org-viewer',
        content_type=org_ct,
    )
    org_viewer_rd.give_permission(team, organization)

    # Add rando to the team via the deprecated gateway endpoint (the old API path).
    # This must create a RoleUserAssignment via give_permission(), not a raw M2M add.
    associate_url = get_relative_url('team-users-associate', kwargs={'pk': team.pk})
    response = admin_api_client.post(associate_url, data={'instances': [rando.id]})
    assert response.status_code == 204, f"Associate call failed: {response.data}"

    # A RoleUserAssignment must exist for rando on the team (TeamMember role).
    # Without this, the RBAC evaluation chain is broken and role_user_access won't show rando.
    team_member_rd = RoleDefinition.objects.get(name='Team Member')
    assert RoleUserAssignment.objects.filter(user=rando, role_definition=team_member_rd).exists(), (
        "No RoleUserAssignment created for rando after team-users-associate — perform_associate must call give_permission(), not the raw M2M manager"
    )

    # Check that rando appears in role_user_access for the organization.
    access_url = reverse('role-user-access', kwargs={'pk': organization.pk, 'model_name': 'shared.organization'})
    response = admin_api_client.get(access_url)
    assert response.status_code == 200

    usernames = {u['username'] for u in response.data['results']}
    assert rando.username in usernames, f"rando not found in role_user_access after being added to team via old API. Found users: {usernames}"

    # The access must be attributed to team membership (type='team'), not a direct assignment.
    rando_entry = next(u for u in response.data['results'] if u['username'] == rando.username)
    assignment_types = [a['type'] for a in rando_entry['object_role_assignments']]
    assert 'team' in assignment_types, f"Expected team-type access for rando, got: {assignment_types}"
