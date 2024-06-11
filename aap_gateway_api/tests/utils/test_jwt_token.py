from functools import partial
from unittest import mock

import pytest
from ansible_base.rbac.models import RoleDefinition
from django.contrib.contenttypes.models import ContentType

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.utils.jwt_token import create_signed_jwt, decode_signed_jwt, get_jwt_rsa_key, get_user_object_roles, update_jwt_public_key


def test_jwt_token_org_ends_up_in_jwt_if_only_team_associated(admin_user, team, set_preference, rsa_keypair):
    RoleDefinition.objects.managed.team_admin.give_permission(admin_user, team)
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)
    jwt_token = create_signed_jwt(admin_user)
    decoded = decode_signed_jwt(jwt_token)
    assert len(decoded['objects']['organization']) == 1


def test_jwt_token_encode_decode(admin_user, set_preference, rsa_keypair, organization, team):
    # Give admin is_systemadmin
    admin_user.apply_system_auditor_membership(True)
    # Give admin a member object permission
    RoleDefinition.objects.managed.org_member.give_permission(admin_user, organization)
    # Give admin an admin object permission
    RoleDefinition.objects.managed.team_admin.give_permission(admin_user, team)

    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)
    jwt_token = create_signed_jwt(admin_user)
    decoded = decode_signed_jwt(jwt_token)
    assert decoded["sub"] == str(admin_user.resource.ansible_id)
    assert decoded['user_data']["email"] == admin_user.email
    assert decoded["iss"] == "ansible-issuer"
    assert decoded["aud"] == "ansible-services"
    assert 'Platform Auditor' in decoded["global_roles"]
    assert 'Organization Member' in decoded['object_roles']
    for content_type, role, ansible_id in [
        ('organization', RoleDefinition.objects.managed.org_member.name, organization.resource.ansible_id),
        ('team', RoleDefinition.objects.managed.team_admin.name, team.resource.ansible_id),
    ]:
        resource_index = None
        for index in range(0, len(decoded['objects'][content_type])):
            resource = decoded['objects'][content_type][index]
            if resource['ansible_id'] == str(ansible_id):
                resource_index = index
        assert resource_index is not None
        assert resource_index in decoded['object_roles'][role]['objects'], f"Missing role? {decoded}"


def test_jwt_token_update_jwt_public_key_private_key_exception(expected_log):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with expected_log("exception", "Unable to load private key from JWT key"):
        with pytest.raises(Exception):
            update_jwt_public_key('junk')


def test_jwt_token_update_jwt_public_key_public_key_exception(expected_log, rsa_keypair):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with mock.patch('aap_gateway_api.utils.preferences.update_preference_value', side_effect=Exception("Failing on purpose")):
        with expected_log("exception", "Unable to export public key from JWT key"):
            with pytest.raises(Exception):
                update_jwt_public_key(rsa_keypair.private)


def test_jwt_token_get_jwt_rsa_key_private(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    assert get_jwt_rsa_key(public=False) == rsa_keypair.private


def test_jwt_token_get_jwt_rsa_key_public(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    assert get_jwt_rsa_key(public=True) == rsa_keypair.public


def test_jwt_token_get_jwt_rsa_key_public_not_set(rsa_keypair, set_preference):
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", '')
    assert get_jwt_rsa_key(public=True) == rsa_keypair.public


@pytest.mark.django_db
class TestUserObjectRoles:
    @property
    def org_ct(self):
        return ContentType.objects.get_for_model(Organization)

    @property
    def team_ct(self):
        return ContentType.objects.get_for_model(Team)

    def test_platform_auditor(self, user):
        RoleDefinition.objects.managed.sys_auditor.give_global_permission(user)
        assert get_user_object_roles(user) == []  # platform auditor is not an object role

    def test_org_admin(self, user, organization):
        RoleDefinition.objects.managed.org_admin.give_permission(user, organization)
        assert get_user_object_roles(user) == [('Organization Admin', str(organization.resource.ansible_id), self.org_ct.id)]

    def test_org_member_team_admin(self, user, organization, team):
        RoleDefinition.objects.managed.org_member.give_permission(user, organization)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team)
        assert set(get_user_object_roles(user)) == {
            ('Organization Member', str(organization.resource.ansible_id), self.org_ct.id),
            ('Team Admin', str(team.resource.ansible_id), self.team_ct.id),
        }

    def test_several_teams_and_orgs(self, user, organization):
        rando = User.objects.create(username='rando')
        expected = set()
        for i in range(5):
            team = Team.objects.create(name=f'team-{i}', organization=organization)
            if i % 3 == 0:
                RoleDefinition.objects.managed.team_admin.give_permission(user, team)
                expected.add(('Team Admin', str(team.resource.ansible_id), self.team_ct.id))
            elif i % 3 == 1:
                RoleDefinition.objects.managed.team_member.give_permission(user, team)
                expected.add(('Team Member', str(team.resource.ansible_id), self.team_ct.id))
                # red herring data
                RoleDefinition.objects.managed.team_admin.give_permission(rando, team)
            else:
                RoleDefinition.objects.managed.team_member.give_permission(rando, team)

        for i in range(5):
            org = Organization.objects.create(name=f'org-{i}')
            if i % 3 == 1:
                RoleDefinition.objects.managed.org_admin.give_permission(user, org)
                expected.add(('Organization Admin', str(org.resource.ansible_id), self.org_ct.id))
            elif i % 3 == 2:
                RoleDefinition.objects.managed.org_member.give_permission(user, org)
                expected.add(('Organization Member', str(org.resource.ansible_id), self.org_ct.id))
                # red herring data
                RoleDefinition.objects.managed.org_member.give_permission(rando, org)
            else:
                RoleDefinition.objects.managed.org_admin.give_permission(rando, org)

        assert len(expected) == 7
        assert set(get_user_object_roles(user)) == expected
