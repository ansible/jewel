from ansible_base.lib.workload_identity import SCOPE_REGISTRY
from oauth2_provider.oauth2_validators import OAuth2Validator

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
        - aap_organizations: [{"name": "...", "role": "admin|member"}, ...]
        - aap_teams: [{"name": "...", "organization": "...", "role": "admin|member"}, ...]
        - aap_system_role: scalar string (system_administrator, system_auditor, or normal_user)
        """
        claims = super().get_userinfo_claims(request)
        user = request.user

        if user and getattr(user, 'is_authenticated', False) and 'roles' in request.scopes:
            from aap_gateway_api.models import Organization, Team

            # Determine org memberships with role type (admin vs member)
            admin_org_ids = set(Organization.access_qs(user, 'change').values_list('pk', flat=True))
            member_orgs = Organization.access_qs(user, 'member')
            claims['aap_organizations'] = [{'name': org.name, 'role': 'admin' if org.pk in admin_org_ids else 'member'} for org in member_orgs]

            # Determine team memberships with role type (admin vs member)
            admin_team_ids = set(Team.access_qs(user, 'change').values_list('pk', flat=True))
            member_teams = Team.access_qs(user, 'member').select_related('organization')
            claims['aap_teams'] = [
                {
                    'name': team.name,
                    'organization': team.organization.name,
                    'role': 'admin' if team.pk in admin_team_ids else 'member',
                }
                for team in member_teams
            ]

            if user.is_superuser:
                claims['aap_system_role'] = 'system_administrator'
            elif getattr(user, 'is_platform_auditor', False):
                claims['aap_system_role'] = 'system_auditor'
            else:
                claims['aap_system_role'] = 'normal_user'

        return claims

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
