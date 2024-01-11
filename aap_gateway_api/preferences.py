from aap_gateway_api.utils import register
from aap_gateway_api.utils.jwt_token import generate_jwt_keypair, update_jwt_public_key

register(
    section="proxy",
    preference_name='gateway_token_name',
    default='X-AAP-GW-TOKEN',
    required=True,
    preference_type="string",
    help_text="The header name to push from the proxy to the backend service. WARNING: if this is changed, backends must be updated to compensate!",
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
    help_text="Enable basic auth to the Gateway API",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url",
    default='https://localhost:9080',
    required=True,
    preference_type="url",
    help_text="URL to the Gateway proxy layer",
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url_ignore_cert",
    default=False,
    required=True,
    preference_type="bool",
    help_text="Ignore certificate to the Gateway proxy layer",
    encrypted=False,
)

default_keypair = generate_jwt_keypair()

register(
    section="proxy",
    preference_name="jwt_private_key",
    default=default_keypair.private,
    required=True,
    preference_type="pem_private_key",
    help_text="JWT private key",
    encrypted=True,
    on_update=lambda preference, old, new: update_jwt_public_key(new),
)

register(
    section="proxy",
    preference_name="jwt_public_key",
    default=default_keypair.public,
    required=False,
    preference_type="longstring",
    help_text="JWT public key (read-only)",
    encrypted=False,
    read_only=True,
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_timeout_seconds",
    default=5,
    required=True,
    preference_type="int",
    help_text="Timeout (in seconds) for the status endpoint to wait when trying to connect to a backend.",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_length",
    default=0,
    required=False,
    preference_type="int",
    help_text="How long does a local password have to be",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_digits",
    default=0,
    required=False,
    preference_type="int",
    help_text="How many numerical characters need to be in a local password",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_upper",
    default=0,
    required=False,
    preference_type="int",
    help_text="How many upper case characters need to be in a local password",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_special",
    default=0,
    required=False,
    preference_type="int",
    help_text="How many special characters need to be in a local password",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="allow_admins_to_set_insecure",
    default=False,
    required=False,
    preference_type="bool",
    help_text="Can a superuser account save an insecure password",
    encrypted=False,
)

register(
    section="social_auth",
    preference_name="SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL",
    default=False,
    required=False,
    preference_type="bool",
    help_text="Enabling this setting will tell social auth to use the full email as username instead of the full name",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="LOGIN_REDIRECT_OVERRIDE",
    default='',
    required=False,
    preference_type="url",
    help_text="URL to which unauthorized users will be redirected to log in. If blank, users will be sent to the login page.",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_login_info",
    default="",
    required=False,
    preference_type="longstring",
    help_text="Provide a specific information (such as a legal notice or a disclaimer) to a text box in the login modal",
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_logo",
    required=False,
    default="",
    preference_type="image",
    help_text="Provide an image file for setting up a custom logo (must be a data URL with a base64-encoded GIF, PNG or JPEG image)",
    encrypted=False,
)
