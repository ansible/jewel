import pytest
from django.urls import reverse

from aap_gateway_api.models.user import User


def _test_user_no_membership_permissions(user_api_client, user, users, teams, organizations):
    url = reverse("user-list")
    response = user_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == user.id


def _test_user_team_member_permissions(user_api_client, user, users, teams, organizations):
    """User is Team Member of # Team 1 (Org 1), # Team 3 (Org 2)"""
    teams[organizations[0]][0].users.add(user)  # Team 1 (Org 1)
    teams[organizations[1]][0].users.add(user)  # Team 3 (Org 2)

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200

    visible_users = _get_visible_users_by_name(response.data['results'])
    #
    # User doesn't see other team members
    #
    expected_users = _get_expected_users_by_name(user, [])
    assert set(visible_users) == set(expected_users)

    teams[organizations[0]][0].users.remove(user)  # Team 1 (Org 1)
    teams[organizations[1]][0].users.remove(user)  # Team 3 (Org 2)


def _test_user_team_admin_permissions(user_api_client, user, users, teams, organizations):
    """
    User is Team Admin of Team 1 (Org 1), Team 3 (Org 2)
    User is Team Member of Team 4 (Org 2), Team 5 (Org 3) (should have no effect)
    """
    teams[organizations[0]][0].admins.add(user)  # Team 1 (Org 1)
    teams[organizations[1]][0].admins.add(user)  # Team 3 (Org 2)
    teams[organizations[1]][1].users.add(user)  # Team 4 (Org 2)
    teams[organizations[2]][0].users.add(user)  # Team 5 (Org 3)

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200

    visible_usernames = _get_visible_users_by_name(response.data['results'])
    #
    # User doesn't see other team members
    #
    expected_usernames = _get_expected_users_by_name(user, [])
    assert set(visible_usernames) == set(expected_usernames)

    teams[organizations[0]][0].admins.remove(user)  # Team 1 (Org 1)
    teams[organizations[1]][0].admins.remove(user)  # Team 3 (Org 2)
    teams[organizations[1]][1].users.remove(user)  # Team 4 (Org 2)
    teams[organizations[2]][0].users.remove(user)  # Team 5 (Org 3)


def _test_user_org_member_permissions(user_api_client, user, users, teams, organizations):
    organizations[0].users.add(user)  # Org 1
    organizations[1].users.add(user)  # Org 2

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200

    visible_usernames = _get_visible_users_by_name(response.data['results'])
    #
    # Org Member sees other Org Members in the same org
    #
    expected_orgs = [organizations[0], organizations[1]]
    expected_users = []
    for org in expected_orgs:
        expected_users.extend(users[org])

    expected_usernames = _get_expected_users_by_name(user, expected_users)
    assert set(visible_usernames) == set(expected_usernames)

    organizations[0].users.remove(user)  # Org 1
    organizations[1].users.remove(user)  # Org 2


def _test_user_org_admin_permissions(user_api_client, user, users, teams, organizations):
    """
    User is Org Admin of Org 1
    """
    organizations[0].admins.add(user)  # Org 1

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200
    #
    # Org Admin sees all users
    #
    cnt = User.objects.count()
    assert response.data['count'] == cnt

    organizations[0].admins.remove(user)  # Org 1


def _test_user_system_auditor_permissions(user_api_client, user, users, teams, organizations):
    user.is_system_auditor = True
    user.save()

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200

    #
    # System Auditor sees all users
    #
    cnt = User.objects.count()
    assert response.data['count'] == cnt

    user.is_system_auditor = False
    user.save()


def _test_user_superuser_permissions(user_api_client, user, users, teams, organizations):
    user.is_superuser = True
    user.save()

    url = reverse("user-list")
    response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
    assert response.status_code == 200

    #
    # Superuser sees all users
    #
    cnt = User.objects.count()
    assert response.data['count'] == cnt

    user.is_superuser = False
    user.save()


@pytest.mark.django_db
def test_user_list_permissions(user_api_client, user, users, teams, organizations):  # noqa: F811
    _test_user_no_membership_permissions(user_api_client, user, users, teams, organizations)

    # Because django db doesn't support fixtures with scope='module'
    # It's better to do everything in 1 test

    associate_users(users, teams, organizations)

    _test_user_team_member_permissions(user_api_client, user, users, teams, organizations)
    _test_user_team_admin_permissions(user_api_client, user, users, teams, organizations)
    _test_user_org_member_permissions(user_api_client, user, users, teams, organizations)
    _test_user_org_admin_permissions(user_api_client, user, users, teams, organizations)
    _test_user_system_auditor_permissions(user_api_client, user, users, teams, organizations)
    _test_user_superuser_permissions(user_api_client, user, users, teams, organizations)


class TestRelatedUserListView:
    def _initial_check(self, url, user_api_client, count=0):
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == count

    def _assign_users(self, role_definition, object):
        members = [
            User.objects.create(username='rando1'),
            User.objects.create(username='rando2'),
            User.objects.create(username='rando3'),
        ]
        role_definition.give_permission(members[0], object)
        role_definition.give_permission(members[1], object)

    def test_org_admin_list_org_members(self, user, user_api_client, organization, org_member_rd, org_admin_rd):
        org_admin_rd.give_permission(user, organization)

        url = reverse('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 2

    def test_org_member_list_org_members(self, user, user_api_client, organization, org_member_rd):
        org_member_rd.give_permission(user, organization)

        url = reverse('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client, 1)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 3

    def test_superadmin_list_org_members(self, user, user_api_client, organization, org_member_rd):
        user.is_superuser = True
        user.save()

        url = reverse('organization-users-list', kwargs={'pk': organization.pk})
        self._initial_check(url, user_api_client)
        self._assign_users(org_member_rd, organization)

        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 2


@pytest.mark.django_db
class TestUserOptions:
    def test_users_list_options_user(self, user_api_client):
        url = reverse("user-list")
        response = user_api_client.options(url)
        assert response.status_code == 200, "Options for list users should be available for standard user"
        assert response.data.get('actions', {}).get('POST', None) is None, "POST action for users should be forbidden for standard user"

    def test_users_list_options_system_auditor(self, user_api_client, user):
        user.is_system_auditor = True
        user.save()

        url = reverse("user-list")
        response = user_api_client.options(url)
        assert response.status_code == 200, "Options for list users should be available for auditor"
        assert response.data.get('actions', {}).get('POST', None) is None, "POST action for user shouldn't be available for auditor"

    def test_users_list_options_superuser(self, admin_api_client):
        url = reverse("user-list")
        response = admin_api_client.options(url)
        assert response.status_code == 200, "Options for list users should be available for superuser"
        assert response.data.get('actions', {}).get('POST', None) is not None, "POST action for users should be available for superuser"

    def test_users_detail_options_user(self, user_api_client, user, organization, team, org_admin_rd, org_member_rd, admin_rd, member_rd):
        url = reverse("user-detail", kwargs={"pk": user.pk})
        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is not None, "user should be able to change self"

        user2 = User.objects.create(username='another user')
        url = reverse("user-detail", kwargs={"pk": user2.pk})

        # Two unrelated users
        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for non-visible user"

        # Team Members
        member_rd.give_permission(user, team)
        member_rd.give_permission(user2, team)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for non-visible user"

        # Team Admin + Team Member
        member_rd.remove_permission(user, team)
        admin_rd.give_permission(user, team)

        response = user_api_client.options(url)
        assert response.status_code == 200, "Team Admin should see OPTIONS of Team Member"
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for Team Admin"

        # Org Members
        for u in [user, user2]:
            member_rd.remove_permission(u, team)
            admin_rd.remove_permission(u, team)
            org_member_rd.give_permission(u, organization)

        response = user_api_client.options(url)
        assert response.status_code == 200, "Org Member should see OPTIONS of another Org Member"
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for Org Member"

        # Org Admin + Org Member
        org_member_rd.remove_permission(user, organization)
        org_admin_rd.give_permission(user, organization)

        assert response.status_code == 200, "Org Admin should see OPTIONS of Org Member"
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for Org Admin"

        # Org Admin + Team Member
        org_member_rd.remove_permission(user2, organization)
        member_rd.give_permission(user2, team)

        assert response.status_code == 200, "Org Admin should see OPTIONS of Team Member"
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for Org Admin on Team Member"

    def test_users_detail_options_system_auditor(self, user_api_client, user):
        user.is_system_auditor = True
        user.save()

        url1 = reverse("user-detail", kwargs={"pk": user.pk})
        response = user_api_client.options(url1)
        assert response.status_code == 200, "System Auditor should see OPTIONS for self"
        assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action should be available for auditor"

        user2 = User.objects.create(username='another user')
        url2 = reverse("user-detail", kwargs={"pk": user2.pk})
        response = user_api_client.options(url2)
        assert response.status_code == 200, "System Auditor should see OPTIONS for 'another user'"
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for auditor"

    def test_users_detail_options_superuser(self, admin_api_client):
        user2 = User.objects.create(username='another user')
        url = reverse("user-detail", kwargs={"pk": user2.pk})

        response = admin_api_client.options(url)
        assert response.status_code == 200, "Options for 'another user' should be available for superuser"
        assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action for should be available for superuser"


def _get_visible_users_by_name(response_data):
    visible_users = [user["username"] for user in response_data]
    return visible_users


def _get_expected_users_by_name(request_user, data):
    expected_users = [user.username for user in data]
    expected_users.append(request_user.username)

    return expected_users


def associate_users(users, teams, organizations):
    """Making memberships:
    Each Team has:
    - 1 Team Member
    - 1 Team Admin
    - 1 Team Member+Admin
    Each Org has:
    - 1 Org Member
    - 1 Org Admin
    - 1 Org Member+Admin
    """
    for org in organizations:
        for org_team in teams[org]:
            for i, team_user in enumerate(users[org_team], 1):
                if i == 1:
                    # Add Team Member
                    org_team.users.add(team_user)
                elif i == 2:
                    # Add Team Admin
                    org_team.admins.add(team_user)
                elif i == 3:
                    # Add Team Member+Admin
                    org_team.users.add(team_user)
                    org_team.admins.add(team_user)

        for i, org_user in enumerate(users[org], 1):
            if i == 1:
                # Add Org Member
                org.users.add(org_user)
            elif i == 2:
                # Add Org Admin
                org.admins.add(org_user)
            elif i == 3:
                # Add Org Member+Admin
                org.users.add(org_user)
                org.admins.add(org_user)
