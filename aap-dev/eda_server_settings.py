# This file will be the django settings entry point
# By importing development we respect the default eda-server dev django settings entrypoint
from .development import *

ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
ALLOW_LOCAL_RESOURCE_MANAGEMENT = False
ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {'platform_auditor': {'name': 'Platform Auditor', 'shortname': 'sys_auditor'}}
