import contextlib
from abc import abstractmethod

import pytest
from django.urls import reverse

from aap_gateway_api.models.user import User
from aap_gateway_api.tests.functional.rbac.conftest import associate_users
from aap_gateway_api.utils.rbac import get_system_auditor_role


@pytest.mark.django_db
class TestSystemAuditorSync:
    def test_role_to_flag(self):
        alice = User.objects.create(username='alice')
        rd = get_system_auditor_role()
        rd.give_global_permission(alice)
        assert alice.role_assignments.filter(role_definition=rd).exists()  # sanity

        alice.refresh_from_db()
        assert alice.is_system_auditor is True

    def test_flag_to_role(self):
        alice = User.objects.create(username='alice')
        alice.is_system_auditor = True
        alice.save()

        rd = get_system_auditor_role()
        assert alice.role_assignments.filter(role_definition=rd).exists()

    def test_create_system_auditor1(self):
        alice = User(username='alice', is_system_auditor=True)
        assert not alice.pk
        assert alice._is_system_auditor
        alice.save()
        rd = get_system_auditor_role()
        assert alice.role_assignments.filter(role_definition=rd).exists()

    def test_del_cached_value(self):
        alice = User.objects.create(username='alice', is_system_auditor=True)
        assert alice._is_system_auditor

        rd = get_system_auditor_role()
        alice.role_assignments.filter(role_definition=rd).delete()

        del alice.is_system_auditor
        assert alice.is_system_auditor is False

    def test_create_system_auditor2(self):
        alice = User.objects.create(username='alice', is_system_auditor=True)
        rd = get_system_auditor_role()
        assert alice.role_assignments.filter(role_definition=rd).exists()


class TestUserPermissionsBase:
    ROLE_NAME = "---"

    @pytest.fixture(scope="function", autouse=True)
    def init_db(self, users, teams, organizations):
        associate_users(users, teams, organizations)

    def _test_permissions(self, user_api_client, user, users, teams, organizations):
        self._test_list(user_api_client, user, users, teams, organizations)
        self._test_detail(user_api_client, user, users, teams, organizations)
        self._test_create(user_api_client, user, users, teams, organizations)
        self._test_update(user_api_client, user, users, teams, organizations)
        self._test_delete(user_api_client, user, users, teams, organizations)

    @abstractmethod
    def _test_list(self, user_api_client, user, users, teams, organizations):
        pass

    @abstractmethod
    def _test_detail(self, user_api_client, user, users, teams, organizations):
        pass

    @abstractmethod
    def _test_create(self, user_api_client, user, users, teams, organizations):
        pass

    @abstractmethod
    def _test_update(self, user_api_client, user, users, teams, organizations):
        pass

    @abstractmethod
    def _test_delete(self, user_api_client, user, users, teams, organizations):
        pass

    def _test_detail_see_all(self, user_api_client, users, teams, organizations):
        # Some random users
        accessed_users = users[organizations[0]] + [users[organizations[1]][0]] + [users[teams[organizations[0]][0]][0]]
        for accessed_user in accessed_users:
            url = reverse("user-detail", kwargs={"pk": accessed_user.pk})
            response = user_api_client.get(url)
            assert response.status_code == 200, f"{self.ROLE_NAME} should see {accessed_user}"

    def _test_create_one(self, user_api_client, status_code, superuser=False):
        url = reverse("user-list")
        data = {
            "username": "new-testing-user",
            "password": "password",
            "email": "testmail@localhost",
            "first_name": "",
            "last_name": "",
            "is_superuser": superuser,
        }
        response = user_api_client.post(url, data)
        assert response.status_code == status_code, f"{self.ROLE_NAME} should POST with status code {status_code}"

        if status_code == 201:
            user = User.objects.get(username=data["username"])
            user.delete()

    def _test_update_one(self, user_api_client, target_user, status_code):
        url = reverse("user-detail", kwargs={"pk": target_user.pk})
        data = {"password": "new_password"}

        response = user_api_client.patch(url, data)
        assert response.status_code == status_code, f"{self.ROLE_NAME} should PATCH with status code {status_code} | {response.data}"

    def _test_delete_one(self, user_api_client, target_user, status_code):
        url = reverse("user-detail", kwargs={"pk": target_user.pk})

        response = user_api_client.delete(url)
        assert response.status_code == status_code, f"{self.ROLE_NAME} should DELETE with status code {status_code}"


@pytest.mark.django_db
class TestUserUnauthenticatedPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Unauthenticated"

    def test_permissions(self, unauthenticated_api_client, user, users, teams, organizations):
        self._test_permissions(unauthenticated_api_client, user, users, teams, organizations)

    def _test_list(self, unauthenticated_api_client, user, users, teams, organizations):
        """Unauthenticated user can't list"""
        url = reverse("user-list")
        response = unauthenticated_api_client.get(url)
        assert response.status_code == 401

    def _test_detail(self, unauthenticated_api_client, user, users, teams, organizations):
        """Unauthenticated can't see user detail"""
        url = reverse("user-detail", kwargs={"pk": user.pk})
        response = unauthenticated_api_client.get(url)
        assert response.status_code == 401

    def _test_create(self, unauthenticated_api_client, user, users, teams, organizations):
        """Unauthenticated user can't create user"""
        self._test_create_one(unauthenticated_api_client, status_code=401)

    def _test_update(self, unauthenticated_api_client, user, users, teams, organizations):
        """Unauthenticated user can't update any user"""
        org = organizations[0]
        self._test_update_one(unauthenticated_api_client, users[org][0], status_code=401)

    def _test_delete(self, unauthenticated_api_client, user, users, teams, organizations):
        """Unauthenticated user can't delete any user"""
        org = organizations[0]
        self._test_delete_one(unauthenticated_api_client, users[org][0], status_code=401)


@pytest.mark.django_db
class TestUserNoRolePermissions(TestUserPermissionsBase):
    ROLE_NAME = "Basic user"

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Basic user sees self and superusers"""
        url = reverse("user-list")
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 1
        assert response.data['results'][0]['id'] == user.id

        another_user = users[None][0]
        another_user.is_superuser = True
        another_user.save()
        response = user_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] == 2
        another_user.is_superuser = False
        another_user.save()

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Basic user sees self and superusers"""
        url = reverse("user-detail", kwargs={"pk": user.pk})
        response = user_api_client.get(url)
        assert response.status_code == 200

        another_user = users[None][1]
        url = reverse("user-detail", kwargs={"pk": another_user.pk})
        response = user_api_client.get(url)
        assert response.status_code == 404

        another_user.is_superuser = True
        another_user.save()
        response = user_api_client.get(url)
        assert response.status_code == 200
        another_user.is_superuser = False
        another_user.save()

    def _test_create(self, user_api_client, user, users, teams, organizations):
        """Basic user can't create user"""
        self._test_create_one(user_api_client, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Basic user can't update any other user, but can update self"""
        org = organizations[0]
        for org_member in users[org]:
            self._test_update_one(user_api_client, org_member, status_code=404)

        self._test_update_one(user_api_client, user, status_code=200)

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Basic user can't delete any user"""
        org = organizations[0]
        for org_member in users[org]:
            self._test_delete_one(user_api_client, org_member, status_code=401)

        self._test_delete_one(user_api_client, user, status_code=401)


@pytest.mark.django_db
class TestUserTeamMemberPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Team Member"

    @staticmethod
    @contextlib.contextmanager
    def team_member_scope(organizations, teams, user):
        """User is Team Member of Team 1 (Org 1), Team 3 (Org 2)"""
        try:
            teams[organizations[0]][0].users.add(user)  # Team 1 (Org 1)
            teams[organizations[1]][0].users.add(user)  # Team 3 (Org 2)
            yield
        finally:
            teams[organizations[0]][0].users.remove(user)  # Team 1 (Org 1)
            teams[organizations[1]][0].users.remove(user)  # Team 3 (Org 2)

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.team_member_scope(organizations, teams, user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Team Member doesn't see other team members"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        visible_users = _get_visible_users_by_name(response.data['results'])
        expected_users = _get_expected_users_by_name(user, [])
        assert set(visible_users) == set(expected_users)

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Team Member doesn't see other users from the same team"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            url = reverse("user-detail", kwargs={"pk": team_member.pk})
            response = user_api_client.get(url)
            assert response.status_code == 404

    def _test_create(self, user_api_client, user, users, teams, organizations):
        """Team Member can't create user"""
        self._test_create_one(user_api_client, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Team Member can't update any other user"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            self._test_update_one(user_api_client, team_member, status_code=404)

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Team Member can't delete any other user"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            self._test_delete_one(user_api_client, team_member, status_code=404)


@pytest.mark.django_db
class TestUserTeamAdminPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Team Admin"

    @staticmethod
    @contextlib.contextmanager
    def team_admin_scope(organizations, teams, user):
        """
        User is Team Admin of Team 1 (Org 1), Team 3 (Org 2)
        User is Team Member of Team 4 (Org 2), Team 5 (Org 3) (should have no effect)
        """
        try:
            teams[organizations[0]][0].admins.add(user)  # Team 1 (Org 1)
            teams[organizations[1]][0].admins.add(user)  # Team 3 (Org 2)
            teams[organizations[1]][1].users.add(user)  # Team 4 (Org 2)
            teams[organizations[2]][0].users.add(user)  # Team 5 (Org 3)
            yield
        finally:
            teams[organizations[0]][0].admins.remove(user)  # Team 1 (Org 1)
            teams[organizations[1]][0].admins.remove(user)  # Team 3 (Org 2)
            teams[organizations[1]][1].users.remove(user)  # Team 4 (Org 2)
            teams[organizations[2]][0].users.remove(user)  # Team 5 (Org 3)

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.team_admin_scope(organizations, teams, user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Team Admin doesn't see other users"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        visible_usernames = _get_visible_users_by_name(response.data['results'])
        expected_usernames = _get_expected_users_by_name(user, [])
        assert set(visible_usernames) == set(expected_usernames)

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Team Admin doesn't see other users from the same team"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            url = reverse("user-detail", kwargs={"pk": team_member.pk})
            response = user_api_client.get(url)
            assert response.status_code == 404

    def _test_create(self, user_api_client, user, users, teams, organizations):
        """Team Admin can't create user"""
        self._test_create_one(user_api_client, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Team Admin can't update any other user"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            self._test_update_one(user_api_client, team_member, status_code=404)

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Team Admin can't delete any other user"""
        same_team = teams[organizations[0]][0]
        for team_member in users[same_team]:
            self._test_delete_one(user_api_client, team_member, status_code=404)


@pytest.mark.django_db
class TestUserOrgMemberPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Org Member"

    @staticmethod
    @contextlib.contextmanager
    def org_member_scope(organizations, user):
        """User is Org Member of Org 1, Org 2"""
        try:
            organizations[0].users.add(user)  # Org 1
            organizations[1].users.add(user)  # Org 2
            yield
        finally:
            organizations[0].users.remove(user)  # Org 1
            organizations[1].users.remove(user)  # Org 2

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.org_member_scope(organizations, user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Org Member sees other Org Members in the same org"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        visible_usernames = _get_visible_users_by_name(response.data['results'])

        expected_orgs = [organizations[0], organizations[1]]
        expected_users = []
        for org in expected_orgs:
            expected_users.extend(users[org])

        expected_usernames = _get_expected_users_by_name(user, expected_users)
        assert set(visible_usernames) == set(expected_usernames)

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Org Member does see other users from the same org"""
        same_org, different_org = organizations[0], organizations[5]

        for same_org_member in users[same_org]:
            url = reverse("user-detail", kwargs={"pk": same_org_member.pk})
            response = user_api_client.get(url)
            assert response.status_code == 200, same_org_member

        for different_org_member in users[different_org]:
            url = reverse("user-detail", kwargs={"pk": different_org_member.pk})
            response = user_api_client.get(url)
            assert response.status_code == 404, different_org_member

        # Team members of the same organization, who ARE NOT Org Members are not visible
        org_team_member = users[teams[organizations[0]][0]][0]
        url = reverse("user-detail", kwargs={"pk": org_team_member.pk})
        response = user_api_client.get(url)
        assert response.status_code == 404, org_team_member

    def _test_create(self, user_api_client, user, users, teams, organizations):
        self._test_create_one(user_api_client, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Org Member can't update any other user"""
        same_org, different_org = organizations[0], organizations[5]

        # Org Member see member of the same org, but can't update
        self._test_update_one(user_api_client, users[same_org][0], status_code=403)
        # Org Member doesn't see member of different org, thus 404
        self._test_update_one(user_api_client, users[different_org][0], status_code=404)

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Org Member can't delete any other user"""
        same_org, different_org = organizations[0], organizations[5]

        # Org Member see member of the same org, but can't delete
        self._test_delete_one(user_api_client, users[same_org][0], status_code=403)
        # Org Member doesn't see member of different org, thus 404
        self._test_delete_one(user_api_client, users[different_org][0], status_code=404)


@pytest.mark.django_db
class TestUserOrgAdminPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Org Admin"

    @staticmethod
    @contextlib.contextmanager
    def org_admin_scope(organizations, user):
        """User is Org Admin of Org 1"""
        try:
            organizations[0].admins.add(user)  # Org 1
            yield
        finally:
            organizations[0].admins.remove(user)  # Org 1

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.org_admin_scope(organizations, user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Org Admin sees all users"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        cnt = User.objects.count()
        assert response.data['count'] == cnt

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Org Admin sees all users"""
        self._test_detail_see_all(user_api_client, users, teams, organizations)

    def _test_create(self, user_api_client, user, users, teams, organizations):
        """Org Admin can create user"""
        self._test_create_one(user_api_client, status_code=201)

        # Org Admin can't create superuser
        self._test_create_one(user_api_client, superuser=True, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Org Admin can update users from the same org (if they are not superusers)"""
        same_org, different_org = organizations[0], organizations[5]
        team_in_same_org = teams[same_org][0]

        # Org Admin can update Org Member of the same org
        self._test_update_one(user_api_client, users[same_org][0], status_code=200)

        # Org Admin can update Org Admin of the same org
        self._test_update_one(user_api_client, users[same_org][1], status_code=200)

        # Org Admin can't update Team Members of org's team, if they are not Org Members in the same time
        self._test_update_one(user_api_client, users[team_in_same_org][0], status_code=403)

        # Org Admin can't update Org Member of different org
        self._test_update_one(user_api_client, users[different_org][0], status_code=403)

        # When Org Member became also Org Member of different org, Org Admin can't update
        different_org.users.add(users[same_org][0])
        self._test_update_one(user_api_client, users[same_org][0], status_code=403)
        different_org.users.remove(users[same_org][0])

        # Org Admin can't update superuser even if it's member of the same org
        users[same_org][1].is_superuser = True
        users[same_org][1].save()
        self._test_update_one(user_api_client, users[same_org][1], status_code=403)
        users[same_org][1].is_superuser = False
        users[same_org][1].save()

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Org Admin can delete users from the same org (if they are not superusers)"""
        same_org, different_org = organizations[0], organizations[5]
        team_in_same_org = teams[same_org][0]

        # Org Admin can delete Org Member of the same org
        self._test_delete_one(user_api_client, users[same_org][0], status_code=204)

        # Org Admin can delete Org Admin of the same org
        self._test_delete_one(user_api_client, users[same_org][1], status_code=204)

        # Org Admin can't delete Team Members of org's team, if they are not Org Members in the same time
        self._test_delete_one(user_api_client, users[team_in_same_org][0], status_code=403)

        # Org Admin can't delete Org Member of different org
        self._test_delete_one(user_api_client, users[different_org][0], status_code=403)

        # When Org Member became also Org Member of different org, Org Admin can't delete
        different_org.users.add(users[same_org][2])
        self._test_delete_one(user_api_client, users[same_org][2], status_code=403)
        different_org.users.remove(users[same_org][2])

        # Org Admin can't delete superuser even if it's member of the same org
        users[same_org][2].is_superuser = True
        users[same_org][2].save()
        self._test_delete_one(user_api_client, users[same_org][2], status_code=403)
        users[same_org][2].is_superuser = False
        users[same_org][2].save()


@pytest.mark.django_db
class TestUserSystemAuditorPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Platform Auditor"

    @staticmethod
    @contextlib.contextmanager
    def system_auditor_scope(user):
        try:
            user.is_system_auditor = True
            user.save()
            yield
        finally:
            user.is_system_auditor = False
            user.save()

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.system_auditor_scope(user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Platform Auditor sees all users"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        cnt = User.objects.count()
        assert response.data['count'] == cnt

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        """Platform Auditor sees all users"""
        self._test_detail_see_all(user_api_client, users, teams, organizations)

    def _test_create(self, user_api_client, user, users, teams, organizations):
        """Platform Auditor can't create user"""
        self._test_create_one(user_api_client, status_code=403)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Platform Auditor can't update any other user"""
        tested_users = [users[organizations[0]][0], users[teams[organizations[1]][1]][1]]

        for tested_user in tested_users:
            self._test_update_one(user_api_client, tested_user, status_code=403)

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Platform Auditor can't delete any other user"""
        tested_users = [users[organizations[3]][0], users[teams[organizations[4]][1]][1]]

        for tested_user in tested_users:
            self._test_delete_one(user_api_client, tested_user, status_code=403)


@pytest.mark.django_db
class TestUserSuperuserPermissions(TestUserPermissionsBase):
    ROLE_NAME = "Superuser"

    @staticmethod
    @contextlib.contextmanager
    def superuser_scope(user):
        try:
            user.is_superuser = True
            user.save()
            yield
        finally:
            user.is_superuser = False
            user.save()

    def test_permissions(self, user_api_client, user, users, teams, organizations):
        with self.superuser_scope(user):
            self._test_permissions(user_api_client, user, users, teams, organizations)

    def _test_list(self, user_api_client, user, users, teams, organizations):
        """Superuser sees all users"""
        url = reverse("user-list")
        response = user_api_client.get(url, {"order_by": "username", "page_size": 100})
        assert response.status_code == 200

        cnt = User.objects.count()
        assert response.data['count'] == cnt

    def _test_detail(self, user_api_client, user, users, teams, organizations):
        self._test_detail_see_all(user_api_client, users, teams, organizations)

    def _test_create(self, user_api_client, user, users, teams, organizations):
        self._test_create_one(user_api_client, status_code=201)
        self._test_create_one(user_api_client, superuser=True, status_code=201)

    def _test_update(self, user_api_client, user, users, teams, organizations):
        """Superuser can update any other user even with no memberships"""
        tested_users = [users[organizations[0]][0], users[teams[organizations[1]][1]][1], users[None][0]]

        for tested_user in tested_users:
            self._test_update_one(user_api_client, tested_user, status_code=200)

        # Superuser can update other superuser
        users[None][0].is_superuser = True
        users[None][0].save()
        self._test_update_one(user_api_client, users[None][0], status_code=200)
        users[None][0].is_superuser = False
        users[None][0].save()

    def _test_delete(self, user_api_client, user, users, teams, organizations):
        """Superuser can delete any other user even with no memberships"""
        tested_users = [users[organizations[3]][0], users[teams[organizations[4]][1]][1], users[None][0]]

        for tested_user in tested_users:
            self._test_delete_one(user_api_client, tested_user, status_code=204)

        # Superuser can delete other superuser
        users[None][0].is_superuser = True
        users[None][0].save()
        self._test_delete_one(user_api_client, users[None][0], status_code=204)
        users[None][0].is_superuser = False
        users[None][0].save()


@pytest.mark.django_db
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
        assert response.status_code == 200, "Platform Auditor should see OPTIONS for self"
        assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action should be available for auditor"

        user2 = User.objects.create(username='another user')
        url2 = reverse("user-detail", kwargs={"pk": user2.pk})
        response = user_api_client.options(url2)
        assert response.status_code == 200, "Platform Auditor should see OPTIONS for 'another user'"
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
