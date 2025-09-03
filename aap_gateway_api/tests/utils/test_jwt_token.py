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
    assert decoded['sub'] == str(admin_user.resource.ansible_id)
    assert decoded['service_id'] == str(admin_user.resource.service_id)
    # Check that claims_hash is present and is a valid SHA-256 hash
    assert 'claims_hash' in decoded
    assert isinstance(decoded['claims_hash'], str)
    assert len(decoded['claims_hash']) == 64
    assert all(c in '0123456789abcdef' for c in decoded['claims_hash'])


def test_jwt_token_encode_decode(admin_user, set_preference, rsa_keypair, organization, team):
    # Give admin is_systemadmin
    admin_user.apply_platform_auditor_membership(True)
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

    # Check that claims_hash is present and is a valid SHA-256 hash
    assert 'claims_hash' in decoded
    assert isinstance(decoded['claims_hash'], str)
    assert len(decoded['claims_hash']) == 64
    assert all(c in '0123456789abcdef' for c in decoded['claims_hash'])


def test_jwt_token_update_jwt_public_key_private_key_exception(expected_log):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with expected_log("exception", "Unable to load private key from JWT key"):
        with pytest.raises(Exception):
            update_jwt_public_key('junk')


def test_jwt_token_update_jwt_public_key_public_key_exception(expected_log, rsa_keypair):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with mock.patch('aap_gateway_api.utils.jwt_token.update_preference_value', side_effect=Exception("Failing on purpose")):
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
        RoleDefinition.objects.managed.platform_auditor.give_global_permission(user)
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

    def test_unique_orgs_and_teams(self, user, set_preference, rsa_keypair, organization):
        """
        Test that JWT token is generated successfully with multiple team permissions.
        Note: The uniqueness of objects is now validated through the claims hash,
        as the objects data is no longer included in the JWT token itself.
        """

        team1 = Team.objects.create(name="Team 1", organization=organization)
        team2 = Team.objects.create(name="Team 2", organization=organization)
        # Give user team member permission to team 1
        RoleDefinition.objects.managed.team_member.give_permission(user, team1)
        # Give user team member and admin permission to team 2
        RoleDefinition.objects.managed.team_member.give_permission(user, team2)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team2)

        set_preference("proxy", "jwt_private_key", rsa_keypair.private)
        set_preference("proxy", "jwt_public_key", rsa_keypair.public)
        jwt_token = create_signed_jwt(user)
        decoded = decode_signed_jwt(jwt_token)

        # Check that claims_hash is present and is a valid SHA-256 hash
        assert 'claims_hash' in decoded
        assert isinstance(decoded['claims_hash'], str)
        assert len(decoded['claims_hash']) == 64


def test_jwt_token_claims_hash_deterministic(user, set_preference, rsa_keypair, organization, team):
    """Test that the claims hash is deterministic for the same user permissions"""
    RoleDefinition.objects.managed.org_member.give_permission(user, organization)
    RoleDefinition.objects.managed.team_admin.give_permission(user, team)

    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)

    # Create two tokens for the same user
    jwt_token1 = create_signed_jwt(user)
    jwt_token2 = create_signed_jwt(user)

    decoded1 = decode_signed_jwt(jwt_token1)
    decoded2 = decode_signed_jwt(jwt_token2)

    # The claims hash should be identical (though exp timestamps will differ)
    assert decoded1['claims_hash'] == decoded2['claims_hash']


def test_jwt_token_claims_hash_changes_with_permissions(user, set_preference, rsa_keypair, organization):
    """Test that the claims hash changes when user permissions change"""
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)

    # Create token with no permissions
    jwt_token1 = create_signed_jwt(user)
    decoded1 = decode_signed_jwt(jwt_token1)

    # Add a permission
    RoleDefinition.objects.managed.org_member.give_permission(user, organization)

    # Create token with new permission
    jwt_token2 = create_signed_jwt(user)
    decoded2 = decode_signed_jwt(jwt_token2)

    # The claims hash should be different
    assert decoded1['claims_hash'] != decoded2['claims_hash']


def test_jwt_token_with_resource_api_actions(user, set_preference, rsa_keypair):
    """Test that resource_api_actions are included in the JWT token"""
    set_preference("proxy", "jwt_private_key", rsa_keypair.private)
    set_preference("proxy", "jwt_public_key", rsa_keypair.public)

    resource_api_actions = ['list', 'retrieve', 'create', 'update', 'destroy']
    jwt_token = create_signed_jwt(user, resource_api_actions=resource_api_actions)
    decoded = decode_signed_jwt(jwt_token)

    assert 'resource_api_actions' in decoded
    assert set(decoded['resource_api_actions']) == set(resource_api_actions)  # order-agnostic check for extra safety

    # Claims hash should still be present
    assert 'claims_hash' in decoded
    assert isinstance(decoded['claims_hash'], str)
    assert len(decoded['claims_hash']) == 64
