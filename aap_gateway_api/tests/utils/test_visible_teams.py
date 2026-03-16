import pytest
from ansible_base.rbac.models import RoleDefinition
from django.contrib.auth.models import AnonymousUser

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.utils.rbac import visible_teams


@pytest.mark.django_db
class TestVisibleTeams:
    def test_anonymous_user_sees_no_teams(self):
        org = Organization.objects.create(name='Test Org')
        Team.objects.create(name='Test Team', organization=org)

        qs = visible_teams(AnonymousUser())
        assert not qs.exists()

    def test_superuser_sees_all_teams(self, admin_user):
        org1 = Organization.objects.create(name='Org 1')
        org2 = Organization.objects.create(name='Org 2')
        team1 = Team.objects.create(name='Team 1', organization=org1)
        team2 = Team.objects.create(name='Team 2', organization=org2)

        qs = visible_teams(admin_user)
        assert set(qs.values_list('pk', flat=True)) == {team1.pk, team2.pk}

    def test_user_with_no_permissions_sees_no_teams(self):
        org = Organization.objects.create(name='Test Org')
        Team.objects.create(name='Test Team', organization=org)

        user = User.objects.create(username='no-perms')
        qs = visible_teams(user)
        assert not qs.exists()

    def test_org_member_sees_teams_in_own_org_only(self):
        org1 = Organization.objects.create(name='Org 1')
        org2 = Organization.objects.create(name='Org 2')
        team1 = Team.objects.create(name='Team 1', organization=org1)
        Team.objects.create(name='Team 2', organization=org2)

        user = User.objects.create(username='viewer')
        org_member_rd = RoleDefinition.objects.get(name='Organization Member')
        org_member_rd.give_permission(user, org1)

        qs = visible_teams(user)
        assert qs.count() == 1
        assert qs.first().pk == team1.pk

    @pytest.mark.parametrize('org_admins_can_see_all', [True, False])
    def test_org_admin_visibility_depends_on_setting(self, org_admins_can_see_all, preference_manager):
        org1 = Organization.objects.create(name='Org 1')
        org2 = Organization.objects.create(name='Org 2')
        team1 = Team.objects.create(name='Team 1', organization=org1)
        team2 = Team.objects.create(name='Team 2', organization=org2)

        user = User.objects.create(username='org-admin')
        org_admin_rd = RoleDefinition.objects.get(name='Organization Admin')
        org_admin_rd.give_permission(user, org1)

        with preference_manager.set('configuration', 'ORG_ADMINS_CAN_SEE_ALL_USERS', org_admins_can_see_all):
            qs = visible_teams(user)

        if org_admins_can_see_all:
            assert set(qs.values_list('pk', flat=True)) == {team1.pk, team2.pk}
        else:
            assert qs.count() == 1
            assert qs.first().pk == team1.pk

    def test_custom_queryset_is_respected(self, admin_user):
        org1 = Organization.objects.create(name='Org 1')
        org2 = Organization.objects.create(name='Org 2')
        team1 = Team.objects.create(name='Team 1', organization=org1)
        Team.objects.create(name='Team 2', organization=org2)

        custom_qs = Team.objects.filter(name='Team 1')
        qs = visible_teams(admin_user, queryset=custom_qs)
        assert qs.count() == 1
        assert qs.first().pk == team1.pk
