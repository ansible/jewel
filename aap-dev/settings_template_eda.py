# This file will be the django settings entry point
# By importing development we respect the default eda-server dev django settings entrypoint
from .development import *

# This defaults to False but is turned True for normal dev environment
# since we are hooking it up to Gateway, we turn it back to False
ALLOW_SHARED_RESOURCE_CUSTOM_ROLES = False

# Will append the common settings