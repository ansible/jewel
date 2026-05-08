"""Tests for OIDC User Identity PoC (openid and roles scopes)."""

from unittest.mock import MagicMock

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from rest_framework import status

from aap_gateway_api.authentication.workload_scopes_backend import USER_IDENTITY_SCOPES, WorkloadIdentityScopesBackend
from aap_gateway_api.oauth2_validator import ROLE_CLAIMS, USER_IDENTITY_CLAIMS, GatewayOIDCValidator

# -- Discovery endpoint tests --


@pytest.mark.django_db
class TestOIDCDiscoveryUserIdentity:
    @pytest.fixture
    def discovery_url(self):
        return get_relative_url('oauth2_provider:oidc-connect-discovery-info')

    @pytest.mark.parametrize('scope', ['openid', 'roles'])
    def test_scopes_supported_includes_user_identity_scopes(self, admin_api_client, discovery_url, ensure_jwt_keys, scope):
        response = admin_api_client.get(discovery_url)
        assert response.status_code == status.HTTP_200_OK
        assert scope in response.json()['scopes_supported']

    @pytest.mark.parametrize('claim', ['sub', 'preferred_username', 'email', 'name', 'given_name', 'family_name'])
    def test_claims_supported_includes_user_identity_claims(self, admin_api_client, discovery_url, ensure_jwt_keys, claim):
        response = admin_api_client.get(discovery_url)
        assert response.status_code == status.HTTP_200_OK
        assert claim in response.json()['claims_supported']

    @pytest.mark.parametrize('claim', ['aap_organizations', 'aap_teams', 'aap_system_role'])
    def test_claims_supported_includes_role_claims(self, admin_api_client, discovery_url, ensure_jwt_keys, claim):
        response = admin_api_client.get(discovery_url)
        assert response.status_code == status.HTTP_200_OK
        assert claim in response.json()['claims_supported']


# -- Scopes backend tests --


class TestWorkloadIdentityScopesBackendUserIdentity:
    def test_includes_openid_scope(self):
        backend = WorkloadIdentityScopesBackend()
        scopes = backend.get_all_scopes()
        assert 'openid' in scopes

    def test_includes_roles_scope(self):
        backend = WorkloadIdentityScopesBackend()
        scopes = backend.get_all_scopes()
        assert 'roles' in scopes

    def test_openid_and_roles_in_available_scopes(self):
        backend = WorkloadIdentityScopesBackend()
        available = backend.get_available_scopes()
        assert 'openid' in available
        assert 'roles' in available

    def test_user_identity_scopes_have_descriptions(self):
        assert 'openid' in USER_IDENTITY_SCOPES
        assert 'roles' in USER_IDENTITY_SCOPES
        assert len(USER_IDENTITY_SCOPES['openid']) > 0
        assert len(USER_IDENTITY_SCOPES['roles']) > 0


# -- Validator unit tests --


@pytest.mark.django_db
class TestValidatorAdditionalClaims:
    def test_get_additional_claims_returns_user_fields(self, admin_user):
        # Ensure the admin user has profile fields populated for this test
        admin_user.first_name = 'Admin'
        admin_user.last_name = 'User'
        admin_user.email = 'admin@example.com'
        admin_user.save()

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user

        claims = validator.get_additional_claims(request)

        assert claims['sub'] == str(admin_user.resource.ansible_id)
        assert claims['preferred_username'] == admin_user.username
        assert claims['email'] == 'admin@example.com'
        assert claims['name'] == 'Admin User'
        assert claims['given_name'] == 'Admin'
        assert claims['family_name'] == 'User'

    def test_get_additional_claims_empty_fields_omitted(self, user_factory):
        """Per OIDC Core Section 5.1, claims with empty values are omitted."""
        user = user_factory('bare_user', email='', first_name='', last_name='')
        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user

        claims = validator.get_additional_claims(request)

        assert 'email' not in claims
        assert 'given_name' not in claims
        assert 'family_name' not in claims
        assert 'name' not in claims
        # sub and preferred_username are always present
        assert 'sub' in claims
        assert 'preferred_username' in claims

    def test_oidc_claim_scope_mapping(self):
        validator = GatewayOIDCValidator()
        for claim in USER_IDENTITY_CLAIMS:
            assert claim in validator.oidc_claim_scope
            assert validator.oidc_claim_scope[claim] == 'openid'


@pytest.mark.django_db
class TestValidatorUserinfoClaims:
    def test_userinfo_includes_roles_when_scope_granted(self, user_factory, organization, team):
        user = user_factory('member_user')
        RoleDefinition.objects.managed.org_member.give_permission(user, organization)
        RoleDefinition.objects.managed.team_member.give_permission(user, team)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert 'aap_organizations' in claims
        org_entry = next((o for o in claims['aap_organizations'] if o['name'] == organization.name), None)
        assert org_entry is not None
        assert org_entry['roles'] == ['member']
        assert 'aap_teams' in claims
        team_entry = next((t for t in claims['aap_teams'] if t['name'] == team.name), None)
        assert team_entry is not None
        assert team_entry['organization'] == organization.name
        assert team_entry['roles'] == ['member']

    def test_userinfo_excludes_roles_without_scope(self, admin_user):
        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['openid']

        claims = validator.get_userinfo_claims(request)

        assert 'aap_organizations' not in claims
        assert 'aap_teams' not in claims

    def test_userinfo_empty_orgs_and_teams(self, user_factory):
        """User in no orgs/teams returns empty arrays."""
        user = user_factory('lonely_user')
        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_organizations'] == []
        assert claims['aap_teams'] == []

    def test_userinfo_multiple_orgs_and_teams(self, user_factory, organization_factory, team_factory):
        """User with multiple org/team memberships returns all of them."""
        user = user_factory('multi_member')
        org1 = organization_factory('Org Alpha')
        org2 = organization_factory('Org Beta')
        team1 = team_factory('Team X', org1)
        team2 = team_factory('Team Y', org2)

        RoleDefinition.objects.managed.org_member.give_permission(user, org1)
        RoleDefinition.objects.managed.org_member.give_permission(user, org2)
        RoleDefinition.objects.managed.team_member.give_permission(user, team1)
        RoleDefinition.objects.managed.team_member.give_permission(user, team2)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        org_names = {o['name'] for o in claims['aap_organizations']}
        assert org_names == {'Org Alpha', 'Org Beta'}
        for org_entry in claims['aap_organizations']:
            assert org_entry['roles'] == ['member']
        team_names = {t['name'] for t in claims['aap_teams']}
        assert team_names == {'Team X', 'Team Y'}
        for team_entry in claims['aap_teams']:
            assert team_entry['roles'] == ['member']

    def test_userinfo_admin_vs_member_roles(self, user_factory, organization_factory, team_factory):
        """Admin and member roles are correctly distinguished."""
        user = user_factory('role_test_user')
        org_admin = organization_factory('Admin Org')
        org_member = organization_factory('Member Org')
        team_admin = team_factory('Admin Team', org_admin)
        team_member = team_factory('Member Team', org_member)

        RoleDefinition.objects.managed.org_admin.give_permission(user, org_admin)
        RoleDefinition.objects.managed.org_member.give_permission(user, org_member)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team_admin)
        RoleDefinition.objects.managed.team_member.give_permission(user, team_member)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        admin_org = next(o for o in claims['aap_organizations'] if o['name'] == 'Admin Org')
        member_org = next(o for o in claims['aap_organizations'] if o['name'] == 'Member Org')
        assert admin_org['roles'] == ['admin']
        assert member_org['roles'] == ['member']

        admin_team = next(t for t in claims['aap_teams'] if t['name'] == 'Admin Team')
        member_team = next(t for t in claims['aap_teams'] if t['name'] == 'Member Team')
        assert admin_team['roles'] == ['admin']
        assert admin_team['organization'] == 'Admin Org'
        assert member_team['roles'] == ['member']
        assert member_team['organization'] == 'Member Org'

    def test_roles_scope_without_openid(self, admin_user, organization):
        """roles scope without openid still returns org/team data."""
        RoleDefinition.objects.managed.org_member.give_permission(admin_user, organization)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['roles']

        claims = validator.get_userinfo_claims(request)

        assert 'aap_organizations' in claims
        org_names = {o['name'] for o in claims['aap_organizations']}
        assert organization.name in org_names

    def test_system_role_superuser(self, admin_user):
        """Superuser gets system_role = system_administrator."""
        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_system_role'] == 'system_administrator'

    def test_system_role_platform_auditor(self, user_factory):
        """Platform auditor gets system_role = system_auditor."""
        user = user_factory('auditor_user')
        user.is_platform_auditor = True

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_system_role'] == 'system_auditor'

    def test_system_role_normal_user(self, user_factory):
        """Regular user gets system_role = normal_user."""
        user = user_factory('regular_user')

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_system_role'] == 'normal_user'

    def test_system_role_excluded_without_roles_scope(self, admin_user):
        """system_role is absent when roles scope is not granted."""
        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['openid']

        claims = validator.get_userinfo_claims(request)

        assert 'aap_system_role' not in claims

    def test_system_role_platform_auditor_via_validator(self, user_factory):
        """Platform auditor gets system_role=system_auditor.

        The is_platform_auditor flag cannot be set through the standard API,
        so this is only testable at the validator level.
        """
        user = user_factory('auditor_via_validator')
        user.is_platform_auditor = True

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_system_role'] == 'system_auditor'
        assert 'aap_organizations' in claims
        assert 'aap_teams' in claims

    def test_roles_only_scope_returns_role_data_via_validator(self, admin_user, organization):
        """roles scope without openid returns org/team data at the validator level.

        Note: at the API level, /o/userinfo/ returns 401 when only 'roles' scope
        is granted (no 'openid'), because DOT requires 'openid' for the userinfo
        endpoint. This test documents that the validator itself does return role
        data — the 401 is a DOT-level enforcement, not a validator decision.
        """
        RoleDefinition.objects.managed.org_member.give_permission(admin_user, organization)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['roles']

        claims = validator.get_userinfo_claims(request)

        assert 'aap_organizations' in claims
        assert organization.name in {o['name'] for o in claims['aap_organizations']}
        assert 'aap_system_role' in claims

    def test_mixed_admin_member_roles_single_user(self, user_factory, organization_factory):
        """Single user who is admin in one org and member in another simultaneously."""
        user = user_factory('mixed_role_user')
        org_where_admin = organization_factory('Org Where Admin')
        org_where_member = organization_factory('Org Where Member')

        RoleDefinition.objects.managed.org_admin.give_permission(user, org_where_admin)
        RoleDefinition.objects.managed.org_member.give_permission(user, org_where_member)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        admin_entry = next(o for o in claims['aap_organizations'] if o['name'] == 'Org Where Admin')
        member_entry = next(o for o in claims['aap_organizations'] if o['name'] == 'Org Where Member')
        assert admin_entry['roles'] == ['admin']
        assert member_entry['roles'] == ['member']

    def test_special_characters_in_org_team_names(self, user_factory, organization_factory, team_factory):
        """Org/team names with unicode, colons, slashes serialize correctly in claims."""
        user = user_factory('special_char_user')
        org = organization_factory('Org: Ünïcödé / Spëcîal')
        team = team_factory('Team — émojis & slashes/colons:', org)

        RoleDefinition.objects.managed.org_member.give_permission(user, org)
        RoleDefinition.objects.managed.team_member.give_permission(user, team)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        org_entry = next(o for o in claims['aap_organizations'] if o['name'] == org.name)
        assert org_entry is not None
        assert org_entry['name'] == 'Org: Ünïcödé / Spëcîal'

        team_entry = next(t for t in claims['aap_teams'] if t['name'] == team.name)
        assert team_entry is not None
        assert team_entry['name'] == 'Team — émojis & slashes/colons:'
        assert team_entry['organization'] == org.name

    def test_superuser_no_explicit_memberships(self, admin_user, organization_factory, team_factory):
        """Superuser with no explicit org/team assignments gets empty arrays.

        Platform-level access is conveyed by aap_system_role, not org/team claims.
        """
        organization_factory('Org That Exists')
        team_factory('Team That Exists', organization_factory('Another Org'))

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_organizations'] == []
        assert claims['aap_teams'] == []
        assert claims['aap_system_role'] == 'system_administrator'

    def test_superuser_with_explicit_memberships(self, admin_user, organization_factory, team_factory):
        """Superuser with explicit assignments only shows those, not all objects."""
        org_assigned = organization_factory('Assigned Org')
        org_not_assigned = organization_factory('Not Assigned Org')
        team_assigned = team_factory('Assigned Team', org_assigned)
        team_factory('Not Assigned Team', org_not_assigned)

        RoleDefinition.objects.managed.org_member.give_permission(admin_user, org_assigned)
        RoleDefinition.objects.managed.team_member.give_permission(admin_user, team_assigned)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = admin_user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        org_names = {o['name'] for o in claims['aap_organizations']}
        assert org_names == {'Assigned Org'}
        team_names = {t['name'] for t in claims['aap_teams']}
        assert team_names == {'Assigned Team'}
        assert claims['aap_system_role'] == 'system_administrator'

    def test_user_both_admin_and_member_same_org(self, user_factory, organization_factory, team_factory):
        """User with both admin and member roles on the same org/team gets both in roles list."""
        user = user_factory('dual_role_user')
        org = organization_factory('Dual Role Org')
        team = team_factory('Dual Role Team', org)

        RoleDefinition.objects.managed.org_admin.give_permission(user, org)
        RoleDefinition.objects.managed.org_member.give_permission(user, org)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team)
        RoleDefinition.objects.managed.team_member.give_permission(user, team)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        org_entry = next(o for o in claims['aap_organizations'] if o['name'] == 'Dual Role Org')
        assert org_entry['roles'] == ['admin', 'member']

        team_entry = next(t for t in claims['aap_teams'] if t['name'] == 'Dual Role Team')
        assert team_entry['roles'] == ['admin', 'member']

    def test_platform_auditor_only_explicit_memberships(self, user_factory, organization_factory, team_factory):
        """Platform auditor only sees explicit assignments, not all objects."""
        user = user_factory('auditor_explicit')
        user.is_platform_auditor = True
        user.save()

        org_assigned = organization_factory('Auditor Assigned Org')
        org_not_assigned = organization_factory('Auditor Not Assigned Org')
        team_assigned = team_factory('Auditor Assigned Team', org_assigned)
        team_factory('Auditor Not Assigned Team', org_not_assigned)

        RoleDefinition.objects.managed.org_member.give_permission(user, org_assigned)
        RoleDefinition.objects.managed.team_member.give_permission(user, team_assigned)

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert {o['name'] for o in claims['aap_organizations']} == {'Auditor Assigned Org'}
        assert {t['name'] for t in claims['aap_teams']} == {'Auditor Assigned Team'}
        assert claims['aap_system_role'] == 'system_auditor'

    def test_missing_role_definitions_degrades_gracefully(self, user_factory, organization_factory):
        """If managed RoleDefinitions are missing, return empty claims instead of crashing."""
        user = user_factory('missing_rd_user')
        org = organization_factory('Some Org')
        RoleDefinition.objects.managed.org_member.give_permission(user, org)

        RoleDefinition.objects.filter(name='Organization Member').delete()

        validator = GatewayOIDCValidator()
        request = MagicMock()
        request.user = user
        request.scopes = ['openid', 'roles']

        claims = validator.get_userinfo_claims(request)

        assert claims['aap_organizations'] == []
        assert claims['aap_teams'] == []
        assert claims['aap_system_role'] == 'normal_user'


class TestValidatorDiscoveryClaims:
    def test_discovery_claims_include_user_identity(self):
        validator = GatewayOIDCValidator()
        request = MagicMock()
        claims = validator.get_discovery_claims(request)

        for claim in USER_IDENTITY_CLAIMS:
            assert claim in claims

    def test_discovery_claims_include_role_claims(self):
        validator = GatewayOIDCValidator()
        request = MagicMock()
        claims = validator.get_discovery_claims(request)

        for claim in ROLE_CLAIMS:
            assert claim in claims


# -- UserInfo integration tests --


@pytest.mark.django_db
class TestUserInfoEndpoint:
    @pytest.fixture
    def userinfo_url(self):
        return '/o/userinfo/'

    def test_userinfo_returns_standard_claims_with_openid_scope(self, unauthenticated_api_client, oauth2_admin_access_token, admin_user, userinfo_url):
        token_obj = oauth2_admin_access_token[0]
        token_obj.scope = 'openid read'
        token_obj.save()

        response = unauthenticated_api_client.get(
            userinfo_url,
            HTTP_AUTHORIZATION=f'Bearer {oauth2_admin_access_token[1]}',
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data['sub'] == str(admin_user.resource.ansible_id)
        assert data['preferred_username'] == admin_user.username
        assert data['email'] == admin_user.email
        assert 'aap_organizations' not in data
        assert 'aap_teams' not in data

    def test_userinfo_returns_roles_with_openid_roles_scope(
        self, unauthenticated_api_client, oauth2_admin_access_token, admin_user, organization, team, userinfo_url
    ):
        RoleDefinition.objects.managed.org_member.give_permission(admin_user, organization)
        RoleDefinition.objects.managed.team_member.give_permission(admin_user, team)

        token_obj = oauth2_admin_access_token[0]
        token_obj.scope = 'openid roles read'
        token_obj.save()

        response = unauthenticated_api_client.get(
            userinfo_url,
            HTTP_AUTHORIZATION=f'Bearer {oauth2_admin_access_token[1]}',
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data['sub'] == str(admin_user.resource.ansible_id)
        assert data['preferred_username'] == admin_user.username
        assert 'aap_organizations' in data
        org_names = {o['name'] for o in data['aap_organizations']}
        assert organization.name in org_names
        assert 'aap_teams' in data
        team_entry = next((t for t in data['aap_teams'] if t['name'] == team.name), None)
        assert team_entry is not None
        assert team_entry['organization'] == organization.name

    def test_userinfo_requires_authentication(self, unauthenticated_api_client, userinfo_url):
        response = unauthenticated_api_client.get(userinfo_url)
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
