import pytest
from rest_framework.reverse import reverse


class TestRelatedViews:
    @pytest.mark.parametrize(
        "view_name",
        [
            ('user-teams-list'),
            ('user-organizations-list'),
        ],
    )
    def test_user_team_view(self, view_name, admin_api_client, admin_user):
        url = reverse(view_name, kwargs={'pk': admin_user.id})
        response = admin_api_client.get(url)
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "view_name",
        [
            ('user-teams-list'),
            ('user-organizations-list'),
        ],
    )
    def test_user_team_view_invalid_user_id(self, view_name, admin_api_client):
        url = reverse(view_name, kwargs={'pk': 27})
        response = admin_api_client.get(url)
        assert response.status_code == 404


@pytest.mark.parametrize('user_type', ['user', 'team_member', 'team_admin', 'org_member', 'org_admin', 'platform_auditor', 'superuser'])
class TestRelatedViewsBase:
    @pytest.fixture(scope="function", autouse=True)
    def init_user(self, user_type, user_api_client, user, team, organization):
        if user_type in ['platform_auditor', 'superuser']:
            user.is_platform_auditor = user_type == 'platform_auditor'
            user.is_superuser = user_type == 'superuser'
            user.save()
        elif user_type == 'team_member':
            team.add_member(user)
        elif user_type == 'team_admin':
            team.add_admin(user)
        elif user_type == 'org_member':
            organization.add_member(user)
        elif user_type == 'org_admin':
            organization.add_admin(user)

        self.api_client = user_api_client

    def _init_users(self, parent_instance, user_factory):
        members = [user_factory("Member 1"), user_factory("Member 2")]
        admins = [user_factory("Admin 1"), user_factory("Admin 2")]
        _not_member = user_factory("Not-member 1")  # noqa: F841
        superadmin = user_factory("Superuser 1")
        superadmin.is_superuser = True
        superadmin.save()

        for member in members:
            parent_instance.add_member(member)
        for admin in admins:
            parent_instance.add_admin(admin)
        return members, admins

    def _get_ids(self, results):
        return [result['id'] for result in results]


@pytest.mark.django_db
class TestOrganizationRelatedUserViews(TestRelatedViewsBase):
    def test_organization_member_view(self, user_type, user, organization, user_factory):
        members, _ = self._init_users(organization, user_factory)

        url = reverse('organization-users-list', kwargs={'pk': organization.id})
        response = self.api_client.get(url)

        if user_type in ['user', 'team_member', 'team_admin']:
            # Team Member/Admin doesn't see Org Members
            assert response.status_code == 404
        else:
            assert response.status_code == 200
            if user_type == 'org_member':
                assert response.data['count'] == 3, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([member.id for member in members] + [user.id])
            else:
                assert response.data['count'] == 2, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([member.id for member in members])

    def test_organization_admin_view(self, user_type, user, organization, user_factory):
        _, admins = self._init_users(organization, user_factory)

        url = reverse('organization-admins-list', kwargs={'pk': organization.id})
        response = self.api_client.get(url)

        if user_type in ['user', 'team_member', 'team_admin']:
            # Team Member/Admin doesn't see Org Admins
            assert response.status_code == 404
        else:
            assert response.status_code == 200
            if user_type == 'org_admin':
                assert response.data['count'] == 3, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([admin.id for admin in admins] + [user.id])
            else:
                assert response.data['count'] == 2, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([admin.id for admin in admins])


@pytest.mark.django_db
class TestTeamRelatedUserViews(TestRelatedViewsBase):
    def test_team_member_view(self, user_type, user, team, user_factory):
        members, _ = self._init_users(team, user_factory)

        url = reverse('team-users-list', kwargs={'pk': team.id})
        response = self.api_client.get(url)

        if user_type in ['user', 'org_member']:
            # Org Member doesn't see Team Members
            assert response.status_code == 404
        else:
            assert response.status_code == 200

            if user_type == 'team_member':
                # Team Member doesn't see other Team members
                assert response.data['count'] == 1, response.data['results']
                assert response.data['results'][0]['id'] == user.id
            else:
                # Team Admin, Auditor and Superuser see Team members
                assert response.data['count'] == 2, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([member.id for member in members])

    def test_team_admin_view(self, user_type, user, team, user_factory):
        _, admins = self._init_users(team, user_factory)

        url = reverse('team-admins-list', kwargs={'pk': team.id})
        response = self.api_client.get(url)

        if user_type in ['user', 'org_member']:
            assert response.status_code == 404
        else:
            assert response.status_code == 200

            if user_type == 'team_member':
                # Team Member doesn't see Team Admins
                assert response.data['count'] == 0, response.data['results']
            elif user_type == 'team_admin':
                # Team Admin does see all Team Admins (including self)
                assert response.data['count'] == 3, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([admin.id for admin in admins] + [user.id])
            else:
                # Auditor + Superuser see all Team Admins
                assert response.data['count'] == 2, response.data['results']
                assert set(self._get_ids(response.data['results'])) == set([admin.id for admin in admins])

    @pytest.mark.parametrize("api_type", ["old_api", "rbac_api"])
    def test_team_associate_members(self, user_type, user, user_factory, organization, team, api_type):
        rando = user_factory('rando')

        if api_type == "old_api":
            success_code = 204
            url = reverse('team-users-associate', kwargs={'pk': team.pk})
            # data to add rando as a member
            data = {'instances': [rando.id]}
            response = self.api_client.post(url, data=data)
        else:
            success_code = 201
            url = reverse('roleuserassignment-list')
            data = {'object_id': team.pk, 'user': rando.id, 'role_definition': team.member_rd.id}
            response = self.api_client.post(url, data=data)

        # Results have to be the same using RBAC API or deprecated API
        if user_type in ['org_admin', 'superuser']:
            # org admin and superuser can add
            assert team.users.filter(id=rando.id).exists()
            assert response.status_code == success_code, response.data
        else:
            # user can not add rando as a member due to not being able to view that user
            assert not team.users.filter(id=rando.id).exists()

            if user_type == 'user':
                assert response.status_code == (404 if api_type == 'old_api' else 400), response.data
            elif user_type == 'org_member':
                assert response.status_code == (404 if api_type == 'old_api' else 400), response.data
            elif user_type == 'team_member':
                assert response.status_code == (403 if api_type == 'old_api' else 400), response.data
            elif user_type == 'platform_auditor':
                assert response.status_code == 403, response.data
            else:
                assert response.status_code == 400, response.data

        # Team admin can add member when s/he sees him/her
        if user_type == 'team_admin':
            organization.add_member(rando)
            # user still don't see rando so criteria for adding team member is met
            response = self.api_client.post(url, data=data)
            assert not team.users.filter(id=rando.id).exists()
            assert response.status_code == 400, response.data

            organization.add_member(user)
            # user now see rando (and is admin of the team) so criteria for adding team member is met
            response = self.api_client.post(url, data=data)
            assert team.users.filter(id=rando.id).exists()
            assert response.status_code == success_code, response.data

        # Org member cannot add other org member although (s)he sees him/her
        elif user_type == 'org_member':
            organization.add_member(rando)
            # user now see rando, but is not a team admin so criteria for adding team member isn't met
            response = self.api_client.post(url, data=data)
            assert not team.users.filter(id=rando.id).exists()
            # Note: the old API might return also 400
            assert response.status_code == (404 if api_type == 'old_api' else 400), response.data
