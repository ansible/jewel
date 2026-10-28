# External OAuth bearer-token authentication

Gateway can authenticate API requests with an access token issued by a trusted
external OAuth 2.0 or OpenID Connect provider. This is distinct from
browser-based OIDC login: an external bearer token is presented to Gateway in
an API request, validated by Gateway, and is not forwarded to downstream
services.

## Configure an external issuer

Create an enabled authenticator with this type:

```text
ansible_base.authentication.authenticator_plugins.oauth_bearer
```

The authenticator accepts standard requests of the form:

```text
Authorization: Bearer <access-token>
```

Configure the following fields in the authenticator's `configuration`:

| Field | Required | Description |
| --- | --- | --- |
| `ISSUER_URL` | Yes | Exact external issuer expected in the token's `iss` claim. |
| `AUDIENCE` | Yes | Exact audience accepted in the token's `aud` claim. |
| `ID_KEY` | Yes | Stable identity claim, such as `sub` for a user or `azp` for a service principal. |
| `JWKS_URI` or `OIDC_ENDPOINT` | Yes | HTTPS key endpoint, supplied directly or discovered from the issuer. |
| `ALLOWED_ALGORITHMS` | No | Accepted asymmetric signing algorithms; defaults to `RS256`. |
| `GROUPS_CLAIM` | No | Group-membership claim used by authenticator maps; defaults to `groups`. |
| `SCOPE_KEY`, `READ_SCOPE_NAME`, `WRITE_SCOPE_NAME` | No | Token-scope mapping; defaults are `scope`, `read`, and `write`. |
| `USERINFO_URL` | No | Supplemental profile and group-claim endpoint. |
| `EMAIL_KEY`, `FIRST_NAME_KEY`, `LAST_NAME_KEY`, `USERNAME_KEY` | No | Optional mappings from validated claims to local user fields. |

For an OIDC issuer, set `OIDC_ENDPOINT` to the issuer base URL. Gateway uses
the discovery document when the authenticator is saved to populate `JWKS_URI`
and, when present, `USERINFO_URL`. Discovery remains the source of truth while
`OIDC_ENDPOINT` is set. Otherwise, configure `JWKS_URI` directly.

Example configuration:

```json
{
  "ISSUER_URL": "https://idp.example.com/realms/automation",
  "OIDC_ENDPOINT": "https://idp.example.com/realms/automation",
  "AUDIENCE": "gateway-api",
  "ID_KEY": "sub",
  "GROUPS_CLAIM": "groups",
  "ALLOWED_ALGORITHMS": ["RS256"],
  "VERIFY_SSL": true
}
```

Use a provider's access token, not an ID token. Keep `VERIFY_SSL` enabled in
production, require a provider-specific issuer and audience, and restrict
`ALLOWED_ALGORITHMS` to the algorithms your provider uses. Do not configure
Gateway's own OIDC issuer as an external issuer.

## Validation, identity, and authorization

Gateway uses unverified `iss` and `aud` claims only to select a configured
authenticator. It then verifies the token signature, issuer, audience,
expiration, and configured asymmetric algorithm against the provider's JWKS.
`JWT_CLOCK_SKEW_TOLERANCE_SECONDS` defaults to zero and can be set from zero to
300 seconds.

After validation, Gateway creates or updates the local user and provider
association identified by `ID_KEY`, then applies authenticator maps using the
configured group claim. The Gateway system user and inactive users cannot use
this flow. Treat the selected identity claim as stable: changing `ID_KEY` can
create a new local association.

The configured token scopes constrain API access before normal RBAC is applied:
`read` allows safe HTTP methods, `write` allows both read and unsafe methods,
and a token without either configured scope has no scoped API access. Gateway
issued OAuth2 tokens still work; they are handled after external bearer
authenticators decline the credential.

`USERINFO_URL`, when configured, may supply supplementary group and profile
claims. Its response must match the access token subject. A UserInfo outage or
invalid response does not reject an otherwise valid access token; only the
validated access-token claims are used in that case.

## JWKS caching and rotation

Gateway caches provider key sets for `JWKS_CACHE_TIMEOUT` seconds (default
3600; minimum 60). On a signature failure, it can refresh the JWKS once to
handle a provider key rotation. `JWKS_URL_TIMEOUT` controls the request timeout
for the provider key endpoint.

The Gateway preference `authentication.jwks_refresh_cooldown_seconds` controls
how often this forced refresh can occur for a provider. It defaults to 60
seconds and accepts values from 0 through 86400. Set it to `0` only when a
controlled environment requires a refresh for every signature failure; doing
so removes the protection against repeated failed-token refreshes.

## Local Keycloak development

For the bundled development environment, enable Keycloak in
`container-startup.yml`:

```yaml
keycloak_enabled: True
```

Start the stack with `make podman-compose`. Gateway creates a separate
`Dev Keycloak OAuth Bearer Token` authenticator alongside the browser-login
OIDC and SAML authenticators. Mint a test token with:

```bash
make token gateway_admin write
```

Use `read`, `write`, or `none` as the scope argument. `make keycloak-reconcile`
reapplies the local client configuration when necessary. The [Authentication
guide](authentication.md#keycloak-development-environment) contains the full
development-token workflow.
