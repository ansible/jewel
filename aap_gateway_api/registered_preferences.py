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
    label=_('Gateway Token Name'),
)

register(
    section="proxy",
    preference_name="gateway_access_token_expiration",
    default=600,
    required=True,
    preference_type="int",
    help_text=_("How long the access tokens are valid for."),
    encrypted=False,
    label=_('Gateway Access Token Expiration'),
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
    label=_('JWT Expiration Buffer in Seconds'),
)

register(
    section="proxy",
    preference_name="gateway_basic_auth_enabled",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Enable basic auth to the gateway API."),
    encrypted=False,
    label=_('Gateway Basic Auth Enabled'),
)

register(
    section="proxy",
    preference_name="gateway_proxy_url",
    default='https://localhost:9080',
    required=True,
    preference_type="url",
    help_text=_("The URL to the gateway proxy layer."),
    encrypted=False,
    label=_('Gateway Proxy URL'),
)

register(
    section="proxy",
    preference_name="gateway_proxy_url_ignore_cert",
    default=False,
    required=True,
    preference_type="bool",
    help_text=_("Ignore certificate to the gateway proxy layer."),
    encrypted=False,
    label=_('Gateway Proxy URL Ignore Certificate'),
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
    label=_('JWT Private Key'),
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
    label=_('JWT Public Key'),
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_timeout_seconds",
    default=5,
    required=True,
    preference_type="int",
    help_text=_("The timeout (in seconds) for the status endpoint to wait when trying to connect to a backend."),
    encrypted=False,
    label=_('Status Endpoint Backend Timeout in Seconds'),
)

register(
    section="proxy",
    preference_name="status_endpoint_backend_verify",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Should SSL certificates of the services be verified when calling individual nodes for statuses."),
    encrypted=False,
    label=_('Status Endpoint Backend Verify'),
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
    label=_('Resource Client Request Timeout'),
)

register(
    section="proxy",
    preference_name="request_timeout",
    default=30,
    required=True,
    preference_type="int",
    help_text=_("The timeout (in seconds) before the proxy will report a timeout and generate a 504."),
    encrypted=False,
    label=_('Request Timeout'),
)

register(
    section="proxy",
    preference_name="stream_idle_timeout",
    default=60,
    required=True,
    preference_type="int",
    help_text=_(
        "Timeout in seconds for idle streaming connections (e.g., AAP Lightspeed chatbot). Stream is closed if no data is transmitted within this period."
    ),
    encrypted=False,
    label=_('Stream Idle Timeout'),
)

register(
    section="proxy",
    preference_name="max_stream_duration",
    default=3600,
    required=True,
    preference_type="int",
    help_text=_(
        "Maximum total duration in seconds for streaming connections (e.g., AAP Lightspeed chatbot). Stream is closed after this time regardless of activity."
    ),
    encrypted=False,
    label=_('Maximum Stream Duration'),
)

register(
    section="proxy",
    preference_name="trusted_header_timeout",
    default=1000,
    required=True,
    preference_type="int_range",
    help_text=_("The validity period (in milliseconds) for the trusted header."),
    encrypted=False,
    min_value=100,
    max_value=10000,
    label=_('Trusted Header Timeout'),
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
    label=_('Minimum number of characters in local password'),
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
    label=_('Minimum number of numerical digits in local password'),
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
    label=_('Minimum number of uppercase characters in local password'),
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
    label=_('Minimum number of special characters in local password'),
)

register(
    section="local_login",
    preference_name="allow_admins_to_set_insecure",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Can a superuser account save an insecure password."),
    encrypted=False,
    label=_('Allow Platform Admins to Set Insecure User Passwords'),
)

register(
    section="social_auth",
    preference_name="SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_("Enabling this setting will tell social auth to use the full email as username instead of the full name."),
    encrypted=False,
    label=_('Use Email address for usernames'),
)

register(
    section="local_login",
    preference_name="LOGIN_REDIRECT_OVERRIDE",
    default='',
    required=False,
    preference_type="absolute_path_or_url",
    help_text=_("The URL or absolute path to which unauthorized users will be redirected to log in. If blank, users will be sent to the login page."),
    encrypted=False,
    label=_('Login redirect override URL'),
)

register(
    section="local_login",
    preference_name="custom_login_info",
    default="",
    required=False,
    preference_type="longstring",
    help_text=_("Provide specific information (such as a legal notice or a disclaimer) to a text box in the login modal."),
    encrypted=False,
    label=_('Custom Login Information'),
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
    label=_('Session Cookie Age'),
)

register(
    section="configuration",
    preference_name="DEFAULT_PAGE_SIZE",
    required=False,
    default=50,
    preference_type="int",
    help_text=_("The default number of items to show on a list page."),
    encrypted=False,
    label=_('Default Page Size'),
)

register(
    section="configuration",
    preference_name="MAX_PAGE_SIZE",
    required=False,
    default=200,
    preference_type="int",
    help_text=_("The maximum number of items allowed on a list page."),
    encrypted=False,
    label=_('Maximum Page Size'),
)


register(
    section="configuration",
    preference_name="CSRF_TRUSTED_ORIGINS",
    required=False,
    default=[],
    preference_type="CSRF_list",
    help_text=_("List of CSRF trusted origin URLs. Note, if there are values in Djangos CSRF_TRUSTED_ORIGIN, they will always appear in this list."),
    encrypted=False,
    label=_('CSRF Trusted Origins List'),
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
    label=_('Deployment Type'),
)

register(
    section="configuration",
    preference_name="MANAGE_ORGANIZATION_AUTH",
    default=True,
    required=False,
    preference_type="bool",
    help_text=_(
        'Controls whether any Organization Admin has the privileges to create and manage users and teams. '
        'You may want to disable this ability if you are using an LDAP or SAML integration.'
    ),
    encrypted=False,
    label=_('Organization Admins Can Manage Users and Teams'),
)

register(
    section="configuration",
    preference_name="ORG_ADMINS_CAN_SEE_ALL_USERS",
    default=True,
    required=False,
    preference_type="bool",
    help_text=_(
        'Controls whether any Organization Admin can view all users and teams, '
        'even those not associated with their Organization. '
        'When enabled, organization admins can view all users, even users not associated with their organizations. '
        'When disabled, organization admins can only see users from their own organizations, '
    ),
    encrypted=False,
    label=_('All Users Visible to Organization Admins'),
)

register(
    section="oauth2_provider",
    preference_name="ALLOW_OAUTH2_FOR_EXTERNAL_USERS",
    default=False,
    required=False,
    preference_type="bool",
    help_text=_(
        "Enabling this feature allows users who log in via an external provider (e.g., LDAP, SAML) "
        "to create OAuth 2.0 tokens for use with the AAP API. "
        "An AAP token’s lifecycle is managed independently from the external authentication session. "
        "Refer to the 'Manage OAuth2 token creation for external users' section in the "
        "Red Hat Ansible documentation for details."
    ),
    encrypted=False,
    label=_('Allow External Users to Create OAuth2 Tokens'),
)

register(
    section="analytics",
    preference_name="INSIGHTS_TRACKING_STATE",
    default=True,
    required=True,
    preference_type="bool",
    help_text=_("Enables the service to gather data on automation and send it to Automation Analytics."),
    encrypted=False,
    label=_('Gather Insights data for Automation Analytics'),
)

register(
    section="analytics",
    preference_name="RED_HAT_CONSOLE_URL",
    default='https://console.redhat.com',
    required=False,
    preference_type="url",
    help_text=_("This setting is used to to configure the upload URL for data collection for Automation Analytics."),
    encrypted=False,
    label=_('Automation Analytics upload URL'),
)

register(
    section="analytics",
    preference_name="REDHAT_USERNAME",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This username is used to send data to Automation Analytics/"),
    encrypted=False,
    label=_('Red Hat Hybrid Cloud Console Username'),
)

register(
    section="analytics",
    preference_name="REDHAT_PASSWORD",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This password is used to send data to Automation Analytics.'"),
    encrypted=True,
    label=_('Red Hat Hybrid Cloud Console Password'),
)

register(
    section="analytics",
    preference_name="SUBSCRIPTIONS_USERNAME",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This username is used to retrieve subscription and content information."),
    encrypted=False,
    label=_('Subscriptions Username'),
)

register(
    section="analytics",
    preference_name="SUBSCRIPTIONS_PASSWORD",
    default="",
    required=False,
    preference_type="string",
    help_text=_("This password is used to retrieve subscription and content information.'"),
    encrypted=True,
    label=_('Subscriptions Password'),
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
    label=_('Automation Analytics Gather Interval'),
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
    label=_('Notification RSS Feed URL'),
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
    label=_('Notification RSS Feed Enabled'),
)

register(
    section="feature_flags",
    preference_name="RUNTIME_FEATURE_FLAGS",
    required=False,
    default=getattr(settings, "RUNTIME_FEATURE_FLAGS", False),
    preference_type="bool",
    help_text=_(
        "Controls whether toggling of runtime flags is allowed. This is currently set through settings. "
        "If you'd like to change this please update the RUNTIME_FEATURE_FLAGS setting in your configuration."
    ),
    label=_('Runtime Feature Flag Toggling'),
    read_only=True,
    encrypted=False,
    settings_bound=True,
)

register(
    section="feature_flags",
    preference_name="RUNTIME_FEATURE_FLAGS_UI",
    required=False,
    default=getattr(settings, "RUNTIME_FEATURE_FLAGS_UI", False),
    preference_type="bool",
    help_text=_(
        "Controls whether the feature flags UI page is displayed. This is currently set through settings. "
        "If you'd like to change this please update the RUNTIME_FEATURE_FLAGS_UI setting in your configuration."
    ),
    label=_('Feature Flags UI Page'),
    read_only=True,
    encrypted=False,
    settings_bound=True,
)

# Only register OIDC workload identity preferences when feature is enabled
if getattr(settings, 'FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED', False):
    register(
        section="workload_identity",
        preference_name="jwt_default_ttl_seconds",
        default=300,
        required=True,
        preference_type="int",
        help_text=_(
            "Fallback TTL (in seconds) for JWTs issued to jobs without configured timeout. "
            "Default 300s (5 minutes) is appropriate for most workloads. "
            "A 60s clock skew offset is automatically added to ensure token validity. "
            "Adjust based on organizational workload patterns; no hard maximum."
        ),
        encrypted=False,
        label=_('OIDC JWT Fallback TTL (seconds)'),
    )
