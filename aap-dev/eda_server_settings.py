# This file will be the django settings entry point
# By importing development we respect the default eda-server dev django settings entrypoint
from .development import *

ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
