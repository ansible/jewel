# This file will be the django settings entry point
# By importing development we respect the default eda-server dev django settings entrypoint
from .development import *

REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = ['ansible_base.jwt_consumer.eda.auth.EDAJWTAuthentication',] + REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']
ANSIBLE_BASE_JWT_KEY = 'https://aap-gw-proxy-1:9080/'
ANSIBLE_BASE_JWT_VALIDATE_CERT = False
