from aap_gateway_api.utils import register

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
    default=30,
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
    help_text="Enable basic auth to the Gateways API",
    encrypted=False,
)
