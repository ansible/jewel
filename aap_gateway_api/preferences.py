from aap_gateway_api.utils import register
from aap_gateway_api.utils.jwt_token import update_jwt_public_key

register(
    section="proxy",
    preference_name='gateway_token_name',
    default='X-AAP-GW-TOKEN',
    required=True,
    preference_type="string",
    help_text="The header name to push from the proxy to the backend service. WARNING: if this is changed backends must be updated to compensate!",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_access_token_expiration",
    default=600,
    required=True,
    preference_type="int",
    help_text="How long the access tokens are valid for",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_basic_auth_enabled",
    default=True,
    required=True,
    preference_type="bool",
    help_text="Enable basic auth to the gateways API",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url",
    default='https://localhost:8090',
    required=True,
    preference_type="url",
    help_text="URL to the gateway proxy layer",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url_ignore_cert",
    default=True,
    required=True,
    preference_type="bool",
    help_text="Ignore certificate to the gateway proxy layer",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="jwt_private_key",
    default="",
    required=False,
    preference_type="pem_private_key",
    help_text="JWT private key",
    encrypted=True,
    on_update=lambda preference, old, new: update_jwt_public_key(new),
)

register(
    section="proxy",
    preference_name="jwt_public_key",
    default="<key not configured>",
    required=False,
    preference_type="longstring",
    help_text="JWT public key (read-only)",
    encrypted=False,
    read_only=True,
)
