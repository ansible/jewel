import os

from ansible_base.lib.dynamic_config import export, factory, load_envvars, load_python_file_with_injected_context, load_standard_settings_files

from .settings_utils import _GATEWAY_ETC_DIRECTORY, load_custom_envvars, load_grpc_settings, load_oidc_provider_settings, set_secret_key

DYNACONF = factory(
    __name__,
    "GATEWAY",
    # Options passed directly to dynaconf
    settings_files=["defaults.py", "settings_dev.py"],
)

# Load settings from the global settings file if specified in the
# environment, defaulting to /etc/ansible-automation-platform/gateway/settings.py.
settings_file_path = os.environ.get('GATEWAY_SETTINGS_FILE', f'{_GATEWAY_ETC_DIRECTORY}/settings.py')
load_python_file_with_injected_context(settings_file_path, settings=DYNACONF)

load_grpc_settings(DYNACONF)

load_standard_settings_files(DYNACONF)  # /etc/ansible-automation-platform/*.yaml

load_custom_envvars(DYNACONF)  # load custom unprefixed envvars
load_envvars(DYNACONF)  # load envvars prefixed with GATEWAY_
set_secret_key(DYNACONF)  # set secret key based on secret key file

load_oidc_provider_settings(DYNACONF)  # conditionally enable Gateway as OIDC Provider

export(__name__, DYNACONF)  # export back to django.conf.settings
