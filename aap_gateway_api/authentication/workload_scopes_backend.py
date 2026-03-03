from oauth2_provider.scopes import SettingsScopes

from aap_gateway_api.views.api.v1.workload_identity_tokens import SCOPE_REGISTRY


class WorkloadIdentityScopesBackend(SettingsScopes):
    """
    Extends django-oauth-toolkit's SettingsScopes to dynamically include
    workload identity scopes from SCOPE_REGISTRY.
    """

    def get_all_scopes(self):
        base_scopes = dict(super().get_all_scopes())
        workload_scopes = {name: scope_class.description for name, scope_class in SCOPE_REGISTRY.items()}
        return {**base_scopes, **workload_scopes}

    def get_available_scopes(self, application=None, request=None, *args, **kwargs):
        return list(self.get_all_scopes().keys())
