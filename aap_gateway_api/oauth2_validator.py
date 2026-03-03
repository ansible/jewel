from oauth2_provider.oauth2_validators import OAuth2Validator

from aap_gateway_api.views.api.v1.workload_identity_tokens import SCOPE_REGISTRY


class WorkloadIdentityValidator(OAuth2Validator):
    """Extends OAuth2Validator to include workload identity claims in OIDC discovery."""

    def get_discovery_claims(self, request):

        claims = super().get_discovery_claims(request)

        standard_claims = ['iss', 'aud', 'exp', 'iat', 'jti']
        claims.extend(standard_claims)

        for scope_class in SCOPE_REGISTRY.values():
            claims.extend(scope_class.list_claims())

        return sorted(set(claims))
