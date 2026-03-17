from ansible_base.lib.workload_identity import SCOPE_REGISTRY
from ansible_base.oauth2_provider.models.access_token import SCOPES as DAB_SCOPES
from oauth2_provider.scopes import SettingsScopes

# Descriptions for OIDC scopes defined in DAB's SCOPES list.
# Scope names are validated against DAB at import time to prevent drift.
_OIDC_SCOPE_DESCRIPTIONS = {
    'openid': 'OpenID Connect scope — includes standard user identity claims (sub, email, name, etc.)',
    'roles': 'Returns organization and team membership information for the authenticated user',
}
USER_IDENTITY_SCOPES = {scope: _OIDC_SCOPE_DESCRIPTIONS[scope] for scope in _OIDC_SCOPE_DESCRIPTIONS if scope in DAB_SCOPES}


class WorkloadIdentityScopesBackend(SettingsScopes):
    """
    Extends django-oauth-toolkit's SettingsScopes to dynamically include
    workload identity scopes and user identity scopes.
    """

    def get_all_scopes(self):
        base_scopes = dict(super().get_all_scopes())
        workload_scopes = {name: scope_class.description for name, scope_class in SCOPE_REGISTRY.items()}
        return {**base_scopes, **workload_scopes, **USER_IDENTITY_SCOPES}

    def get_available_scopes(self, application=None, request=None, *args, **kwargs):
        return list(self.get_all_scopes().keys())
