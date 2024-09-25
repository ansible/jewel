# Common settings for all services
ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {'platform_auditor': {'name': 'Platform Auditor', 'shortname': 'sys_auditor'}}

# Special and hopefully temporary event 2 settings
ENABLE_SERVICE_BACKED_SSO = True
RESOURCE_SERVER_SYNC_ENABLED = True
ALLOW_LOCAL_RESOURCE_MANAGEMENT = True

# The following line will be replaced by the Makefile logic
# GATEWAY_SERVICE_SECRET

RESOURCE_SERVER = {
    'URL': "https://aap-gw-proxy-1:9080",
    'SECRET_KEY': GATEWAY_SERVICE_SECRET,
    'VALIDATE_HTTPS': False,
}
