import logging

from ansible_base.lib.workload_identity import SCOPE_REGISTRY
from oauth2_provider.oauth2_validators import OAuth2Validator

logger = logging.getLogger('aap_gateway_api.oauth2_validator')

# Standard OIDC user identity claims advertised in discovery
USER_IDENTITY_CLAIMS = ['sub', 'preferred_username', 'email', 'name', 'given_name', 'family_name']

# Role-related claims advertised in discovery
ROLE_CLAIMS = ['aap_organizations', 'aap_teams', 'aap_system_role']


class GatewayOIDCValidator(OAuth2Validator):
    """Extends OAuth2Validator to include workload identity and user identity claims."""

    # Maps each claim to the scope that must be granted for DOT to include it.
    # Derived from USER_IDENTITY_CLAIMS to avoid duplication.
    oidc_claim_scope = dict.fromkeys(USER_IDENTITY_CLAIMS, 'openid')

    def get_additional_claims(self, request):
        """Return standard OIDC user identity claims for ID Tokens.

        Per OIDC Core Section 5.1, claims with empty values are omitted
        rather than returned as empty strings.
        """
        claims = super().get_additional_claims(request)
        user = request.user

        if user and getattr(user, 'is_authenticated', False) and hasattr(user, 'resource'):
            claims['sub'] = str(user.resource.ansible_id)
            claims['preferred_username'] = user.username
            if user.email:
                claims['email'] = user.email
            full_name = user.get_full_name()
            if full_name:
                claims['name'] = full_name
            if user.first_name:
                claims['given_name'] = user.first_name
            if user.last_name:
                claims['family_name'] = user.last_name

        return claims

    def get_userinfo_claims(self, request):
        """Extend UserInfo with role data when the 'roles' scope is granted.

        Role claims use the aap_ prefix to avoid collision with other OIDC providers.
        Structured objects are used instead of flat strings because org/team names
        can contain arbitrary characters (including colons, slashes, etc.):
        - aap_organizations: [{"name": "...", "roles": ["member"]}, ...]
        - aap_teams: [{"name": "...", "organization": "...", "roles": ["member"]}, ...]
        - aap_system_role: scalar string (system_administrator, system_auditor, or normal_user)

        The roles list contains all explicit assignments for a given object
        (e.g. ["admin"], ["member"], or ["admin", "member"] when both are assigned).

        Claims reflect explicit RoleUserAssignment records only; implicit superuser
        access is not included (platform-level access is conveyed by aap_system_role).
        """
        claims = super().get_userinfo_claims(request)
        user = request.user

        if not (user and getattr(user, 'is_authenticated', False) and 'roles' in request.scopes):
            return claims

        org_claims, team_claims = self._build_role_claims(user)
        claims['aap_organizations'] = org_claims
        claims['aap_teams'] = team_claims
        claims['aap_system_role'] = self._get_system_role(user)

        return claims

    @staticmethod
    def _get_system_role(user):
        if user.is_superuser:
            return 'system_administrator'
        if getattr(user, 'is_platform_auditor', False):
            return 'system_auditor'
        return 'normal_user'

    @staticmethod
    def _build_role_claims(user):
        from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment

        from aap_gateway_api.models import Organization, Team

        expected_names = ['Organization Admin', 'Organization Member', 'Team Admin', 'Team Member']
        role_defs = {rd.name: rd for rd in RoleDefinition.objects.filter(name__in=expected_names)}

        missing = set(expected_names) - role_defs.keys()
        if missing:
            logger.error("OIDC role claims unavailable: missing RoleDefinition(s): %s", ', '.join(sorted(missing)))
            return [], []

        org_admin_id = role_defs['Organization Admin'].id
        org_member_id = role_defs['Organization Member'].id
        team_admin_id = role_defs['Team Admin'].id
        team_member_id = role_defs['Team Member'].id

        org_roles = {}
        for obj_id, rd_id in RoleUserAssignment.objects.filter(
            user=user,
            role_definition_id__in=[org_admin_id, org_member_id],
        ).values_list('object_id', 'role_definition_id'):
            org_roles.setdefault(obj_id, set())
            org_roles[obj_id].add('admin' if rd_id == org_admin_id else 'member')

        orgs_by_pk = {str(org.pk): org for org in Organization.objects.filter(pk__in=org_roles.keys())}
        orphaned_orgs = set(org_roles.keys()) - set(orgs_by_pk.keys())
        if orphaned_orgs:
            logger.warning("User %s has RoleUserAssignment(s) for non-existent Organization(s): %s", user.pk, orphaned_orgs)
        org_claims = sorted(
            [{'name': orgs_by_pk[obj_id].name, 'roles': sorted(roles)} for obj_id, roles in org_roles.items() if obj_id in orgs_by_pk],
            key=lambda o: o['name'],
        )

        team_roles = {}
        for obj_id, rd_id in RoleUserAssignment.objects.filter(
            user=user,
            role_definition_id__in=[team_admin_id, team_member_id],
        ).values_list('object_id', 'role_definition_id'):
            team_roles.setdefault(obj_id, set())
            team_roles[obj_id].add('admin' if rd_id == team_admin_id else 'member')

        teams_by_pk = {str(t.pk): t for t in Team.objects.filter(pk__in=team_roles.keys()).select_related('organization')}
        orphaned_teams = set(team_roles.keys()) - set(teams_by_pk.keys())
        if orphaned_teams:
            logger.warning("User %s has RoleUserAssignment(s) for non-existent Team(s): %s", user.pk, orphaned_teams)
        team_claims = sorted(
            [
                {'name': teams_by_pk[obj_id].name, 'organization': teams_by_pk[obj_id].organization.name, 'roles': sorted(roles)}
                for obj_id, roles in team_roles.items()
                if obj_id in teams_by_pk
            ],
            key=lambda t: (t['organization'], t['name']),
        )

        return org_claims, team_claims

    def get_discovery_claims(self, request):
        """Advertise all supported claims in OIDC discovery."""
        claims = super().get_discovery_claims(request)

        standard_claims = ['iss', 'aud', 'exp', 'iat', 'jti']
        claims.extend(standard_claims)

        # Workload identity claims
        for scope_class in SCOPE_REGISTRY.values():
            claims.extend(scope_class.list_claims())

        # User identity claims
        claims.extend(USER_IDENTITY_CLAIMS)
        claims.extend(ROLE_CLAIMS)

        return sorted(set(claims))
