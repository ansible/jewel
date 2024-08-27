# This file will be the django settings entry point
# By importing development we respect the default eda-server dev django settings entrypoint
from .development import *

ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
ALLOW_LOCAL_RESOURCE_MANAGEMENT = True  # Temporary: ATF test-suite needs this setting
ALLOW_LOCAL_ASSIGNING_JWT_ROLES = False
ALLOW_SHARED_RESOURCE_CUSTOM_ROLES = False
ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {'platform_auditor': {'name': 'Platform Auditor', 'shortname': 'sys_auditor'}}

# The following line will be replaced by the Makefile logic
# GATEWAY_SERVICE_SECRET

RESOURCE_SERVER = {
    'URL': "https://aap-gw-proxy-1:9080",
    'SECRET_KEY': GATEWAY_SERVICE_SECRET,
    'VALIDATE_HTTPS': False,
}
