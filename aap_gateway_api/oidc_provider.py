"""
OAuth2/OIDC configuration settings to enable Gateway as an OIDC Provider.

This module is conditionally loaded based on the FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED
install-time feature flag. When enabled, Gateway can issue OIDC tokens for authentication.

"""

# Clock skew offset added to all JWT TTLs to account for time synchronization drift
# between Gateway, external systems, and workload execution environments.
# Value based on RFC 7519 Section 4.1.4 recommendations.
OIDC_JWT_TTL_CLOCK_SKEW_SECONDS = 60


class LazyPrivateKey:
    """Lazily loads the JWT RSA private key for OIDC token signing.

    This class defers loading the private key until it's actually needed,
    avoiding initialization issues during Django startup.
    """

    def encode(self, codec):
        from aap_gateway_api.utils.jwt_token import get_jwt_rsa_key

        return get_jwt_rsa_key().encode(codec)


# Use Dynaconf merge syntax (double underscore) to merge into existing OAUTH2_PROVIDER,
# instead of overwriting it.
OAUTH2_PROVIDER__OIDC_ENABLED = True
OAUTH2_PROVIDER__OIDC_RSA_PRIVATE_KEY = LazyPrivateKey()
OAUTH2_PROVIDER__SCOPES_BACKEND_CLASS = 'aap_gateway_api.authentication.workload_scopes_backend.WorkloadIdentityScopesBackend'
OAUTH2_PROVIDER__OAUTH2_VALIDATOR_CLASS = 'aap_gateway_api.oauth2_validator.WorkloadIdentityValidator'
