from django.conf import settings
from django.utils.translation import gettext as _

from aap_gateway_api.utils import register
from aap_gateway_api.utils.jwt_token import update_jwt_public_key

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
    help_text=_("How long the access tokens are valid for."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="jwt_expiration_buffer_in_seconds",
    default=15,
    required=True,
    preference_type="int",
    help_text=_(
        "Time, in seconds, prior to token expiration time when the token will be removed from cache. "
        "Smaller numbers will increase how long the tokens are kept in cache "
        "however it can increase the chance the token would expire while being used."
    ),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_basic_auth_enabled",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Enable basic auth to the gateway API."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url",
    default='https://localhost:9080',
    required=True,
    preference_type="url",
    help_text=_("The URL to the gateway proxy layer."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="gateway_proxy_url_ignore_cert",
    default=False,
    required=True,
    preference_type="bool",
    help_text=_("Ignore certificate to the gateway proxy layer."),
    encrypted=False,
)

register(
    section="proxy",
    preference_name="jwt_private_key",
    default='',
    required=True,
    preference_type="pem_private_key",
    help_text=_("The JWT private key."),
    encrypted=True,
    on_update=lambda preference, old, new: update_jwt_public_key(new),
)

register(
    section="proxy",
    preference_name="jwt_public_key",
    default='',
    required=False,
    preference_type="longstring",
    help_text=_("The JWT public key (read-only)."),
    encrypted=False,
    read_only=True,
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_timeout_seconds",
    default=5,
    required=True,
    preference_type="int",
    help_text=_("The timeout (in seconds) for the status endpoint to wait when trying to connect to a backend."),
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
    default=10.0,
    required=True,
    preference_type="float_range",
    help_text=_("The timeout (in seconds) before the resource client will drop requests after forming connections."),
    encrypted=False,
    min_value=0.0,
)

register(
    section="proxy",
    preference_name="request_timeout",
    default=30,
    required=True,
    preference_type="int",
    help_text=_("The timeout (in seconds) before the proxy will report a timeout and generate a 504."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="password_min_length",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How long does a local password have to be."),
    encrypted=False,
    min_value=0,
    max_value=100,
    label=_('Password minimum length'),
)

register(
    section="local_login",
    preference_name="password_min_digits",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many numerical characters need to be in a local password."),
    encrypted=False,
    min_value=0,
    max_value=100,
    label=_('Password minimum numerical digits'),
)

register(
    section="local_login",
    preference_name="password_min_upper",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many upper case characters need to be in a local password."),
    encrypted=False,
    min_value=0,
    max_value=100,
    label=_('Password minimum uppercase letters'),
)

register(
    section="local_login",
    preference_name="password_min_special",
    default=0,
    required=False,
    preference_type="int_range",
    help_text=_("How many special characters need to be in a local password."),
    encrypted=False,
    min_value=0,
    max_value=100,
    label=_('Password minimum special characters'),
)

register(
    section="local_login",
    preference_name="allow_admins_to_set_insecure",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Can a superuser account save an insecure password."),
    encrypted=False,
    label=_('Allow system administrators to set insecure user passwords'),
)

register(
    section="social_auth",
    preference_name="SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Enabling this setting will tell social auth to use the full email as username instead of the full name."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="LOGIN_REDIRECT_OVERRIDE",
    default='',
    required=False,
    preference_type="url",
    help_text=_("The URL to which unauthorized users will be redirected to log in. If blank, users will be sent to the login page."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_login_info",
    default="",
    required=False,
    preference_type="longstring",
    help_text=_("Provide specific information (such as a legal notice or a disclaimer) to a text box in the login modal."),
    encrypted=False,
)

register(
    section="local_login",
    preference_name="custom_logo",
    required=False,
    default="",
    preference_type="image",
    help_text=_("Provide an image file for setting up a custom logo (must be a data URL with a base64-encoded GIF, PNG or JPEG image)."),
    encrypted=False,
)

register(
    section="configuration",
    preference_name="SESSION_COOKIE_AGE",
    required=False,
    default=15 * 60,
    preference_type="int_range",
    help_text=_("The time in seconds before a session expires."),
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
    help_text=_("The default number of items to show on a list page."),
    encrypted=False,
)

register(
    section="configuration",
    preference_name="MAX_PAGE_SIZE",
    required=False,
    default=200,
    preference_type="int",
    help_text=_("The maximum number of items allowed on a list page."),
    encrypted=False,
)

register(
    section="configuration",
    preference_name="AAP_DEPLOYMENT_TYPE",
    required=True,
    default=getattr(settings, "AAP_DEPLOYMENT_TYPE", "self-managed"),
    preference_type="string",
    help_text=_("The deployment type for this instance."),
    encrypted=False,
    read_only=True,
    settings_bound=True,
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
    label=_('Allow external users to create OAuth2 tokens'),
)

register(
    section="legacy_sso",
    preference_name="CONTROLLER_SSO_URL",
    default="",
    required=False,
    preference_type="string",
    help_text=_("The URL that is used to kick off authentication for Controller SSO that was configured prior to AAP 2.5."),
    encrypted=False,
)

register(
    section="legacy_sso",
    preference_name="AUTOMATION_HUB_SSO_URL",
    default="",
    required=False,
    preference_type="string",
    help_text=_("The URL that is used to kick off authentication for Automation Hub SSO that was configured prior to AAP 2.5."),
    encrypted=False,
)

register(
    section="analytics",
    preference_name="INSIGHTS_TRACKING_STATE",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Enables the service to gather data on automation and send it to Automation Analytics."),
    encrypted=False,
)

register(
    section="analytics",
    preference_name="RED_HAT_CONSOLE_URL",
    default='https://console.redhat.com',
    required=False,
    preference_type="url",
    help_text=_("This setting is used to to configure the upload URL for data collection for Automation Analytics."),
    encrypted=False,
)

register(
    section="analytics",
    preference_name="REDHAT_USERNAME",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This username is used to send data to Automation Analytics/"),
    encrypted=False,
)

register(
    section="analytics",
    preference_name="REDHAT_PASSWORD",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This password is used to send data to Automation Analytics.'"),
    encrypted=True,
)

register(
    section="analytics",
    preference_name="SUBSCRIPTIONS_USERNAME",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This username is used to retrieve subscription and content information."),
    encrypted=False,
)

register(
    section="analytics",
    preference_name="SUBSCRIPTIONS_PASSWORD",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This password is used to retrieve subscription and content information.'"),
    encrypted=True,
)

register(
    section="analytics",
    preference_name="AUTOMATION_ANALYTICS_GATHER_INTERVAL",
    required=False,
    default=14400,  # every 4 hours
    min_value=1800,  # every 30 minutes
    # There was no max value specified in AWX but our validator max is 100 by default so we need one
    max_value=30000000000,  # approx 1,000 years
    preference_type="int_range",
    help_text=_("The maximum number of items allowed on a list page"),
    encrypted=False,
)

register(
    section="notification",
    preference_name="NOTIFICATION_RSS_FEED_URL",
    required=True,
    default=getattr(settings, "NOTIFICATION_RSS_FEED_URL", "https://announcements.ansiblecloud.redhat.com/feed.atom"),
    preference_type="string",
    help_text=_("URL for RSS feeds from which to load user notifications"),
    encrypted=False,
    read_only=True,
    settings_bound=True,
)

register(
    section="notification",
    preference_name="NOTIFICATION_RSS_FEED_ENABLED",
    required=True,
    default=True,
    preference_type="bool",
    help_text=_("Enable or disable user notifications"),
    encrypted=False,
    read_only=False,
)
