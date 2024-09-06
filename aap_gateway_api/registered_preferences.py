from django.utils.translation import gettext as _

from aap_gateway_api.utils import register
from aap_gateway_api.utils.jwt_token import generate_jwt_keypair, update_jwt_public_key

register(
    section="proxy",
    preference_name='gateway_token_name',
    default='X-DAB-JW-TOKEN',
    required=True,
    preference_type="string",
    help_text=_("The header name to push from the proxy to the backend service. WARNING: if this is changed, backends must be updated to compensate!"),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_access_token_expiration",
    default=600,
    required=True,
    preference_type="int",
    help_text=_("How long the access tokens are valid for"),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="jwt_expiration_buffer_in_seconds",
    default=2,
    required=True,
    preference_type="int",
    help_text=_("The number of seconds before a JWT token's expiration to revoke it from the cache"),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_basic_auth_enabled",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Enable basic auth to the gateway API"),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url",
    default='https://localhost:9080',
    required=True,
    preference_type="url",
    help_text=_("URL to the gateway proxy layer"),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url_ignore_cert",
    default=False,
    required=True,
    preference_type="bool",
    help_text=_("Ignore certificate to the gateway proxy layer"),
    encrypted=False,
)

default_keypair = generate_jwt_keypair()

register(
    section="proxy",
    preference_name="jwt_private_key",
    default=default_keypair.private,
    required=True,
    preference_type="pem_private_key",
    help_text=_("JWT private key"),
    encrypted=True,
    on_update=lambda preference, old, new: update_jwt_public_key(new),
)

register(
    section="proxy",
    preference_name="jwt_public_key",
    default=default_keypair.public,
    required=False,
    preference_type="longstring",
    help_text=_("JWT public key (read-only)"),
    encrypted=False,
    read_only=True,
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_timeout_seconds",
    default=5,
    required=True,
    preference_type="int",
    help_text=_("Timeout (in seconds) for the status endpoint to wait when trying to connect to a backend."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_verify",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Should SSL certificates of the services be verified when calling individual nodes for statuses."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="resource_client_request_timeout",
    default=2.0,
    required=True,
    preference_type="float_range",
    help_text=_("Timeout (in seconds) before the resource client will drop requests after forming connections."),
    encrypted=False,
    min_value=0.0,
)

register(
    section="proxy",
    preference_name="request_timeout",
    default=30,
    required=True,
    preference_type="int",
    help_text=_("Timeout (in seconds) before the proxy will report a timeout and generate a 504."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_length",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How long does a local password have to be"),
    encrypted=False,
    min_value=0,
    max_value=100,
)

register(
    section="local_login",
    preference_name="password_min_digits",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many numerical characters need to be in a local password"),
    encrypted=False,
    min_value=0,
    max_value=100,
)

register(
    section="local_login",
    preference_name="password_min_upper",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many upper case characters need to be in a local password"),
    encrypted=False,
    min_value=0,
    max_value=100,
)

register(
    section="local_login",
    preference_name="password_min_special",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many special characters need to be in a local password"),
    encrypted=False,
    min_value=0,
    max_value=100,
)

register(
    section="local_login",
    preference_name="allow_admins_to_set_insecure",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Can a superuser account save an insecure password"),
    encrypted=False,
)

register(
    section="social_auth",
    preference_name="SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Enabling this setting will tell social auth to use the full email as username instead of the full name"),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="LOGIN_REDIRECT_OVERRIDE",
    default='',
    required=False,
    preference_type="url",
    help_text=_("URL to which unauthorized users will be redirected to log in. If blank, users will be sent to the login page."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_login_info",
    default="",
    required=False,
    preference_type="longstring",
    help_text=_("Provide a specific information (such as a legal notice or a disclaimer) to a text box in the login modal"),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_logo",
    required=False,
    default="",
    preference_type="image",
    help_text=_("Provide an image file for setting up a custom logo (must be a data URL with a base64-encoded GIF, PNG or JPEG image)"),
    encrypted=False,
)

register(
    section="configuration",
    preference_name="SESSION_COOKIE_AGE",
    required=False,
    default=15 * 60,
    preference_type="int_range",
    help_text=_("Time in seconds before a session expires"),
    # We are copying this over directly from AWX to match their settings
    min_value=60,
    max_value=30000000000,  # approx 1,000 years, higher values give OverflowError
)

register(
    section="configuration",
    preference_name="DEFAULT_PAGE_SIZE",
    required=False,
    default=50,
    preference_type="int",
    help_text=_("The default number of items to show on a list page"),
    encrypted=False,
)

register(
    section="configuration",
    preference_name="MAX_PAGE_SIZE",
    required=False,
    default=200,
    preference_type="int",
    help_text=_("The maximum number of items allowed on a list page"),
    encrypted=False,
)

register(
    section="oauth2_provider",
    preference_name="ALLOW_OAUTH2_FOR_EXTERNAL_USERS",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_(
        "For security reasons, users from external auth providers (LDAP, SAML, SSO, Radius, and others) "
        "are not allowed to create OAuth2 tokens. To change this behavior, enable this setting. "
        "Existing tokens will not be deleted when this setting is toggled off."
    ),
    encrypted=False,
)
