import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleUserAssignment

from aap_gateway_api.models import User
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


def _visible_teams(teams, organizations):
    """
    Based on associate_logged_user()
    Org Admins, Team Members and Team Admins can see team
    """
    return [teams[organizations[0]][0], teams[organizations[1]][0], teams[organizations[2]][0], teams[organizations[2]][1]] + teams[organizations[4]]


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
