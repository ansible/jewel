OPTIONAL_API_URLPATTERN_PREFIX = 'controller'
ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
ANSIBLE_BASE_JWT_REDIRECT_TYPE= "awx"
ALLOW_LOCAL_RESOURCE_MANAGEMENT = True  # Temporary: ATF test-suite needs this setting
ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {'platform_auditor': {'name': 'Platform Auditor', 'shortname': 'sys_auditor'}}

# The following line will be replaced by the Makefile logic
# GATEWAY_SERVICE_SECRET

RESOURCE_SERVER = {
    'URL': "https://aap-gw-proxy-1:9080",
    'SECRET_KEY': GATEWAY_SERVICE_SECRET,
    'VALIDATE_HTTPS': False,
}
