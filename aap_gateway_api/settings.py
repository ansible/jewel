import os

from ansible_base.lib.dynamic_config import (
    export,
    factory,
    load_envvars,
    load_python_file_with_injected_context,
    load_standard_settings_files,
    toggle_feature_flags,
)

from .settings_utils import load_custom_envvars, set_secret_key

DYNACONF = factory(
    __name__,
    "GATEWAY",
    # Options passed directly to dynaconf
    settings_files=["defaults.py", "settings_dev.py"],
)

# Load settings from the global settings file if specified in the
# environment, defaulting to /etc/ansible-automation-platform/gateway/settings.py.
settings_file_path = os.environ.get('GATEWAY_SETTINGS_FILE', '/etc/ansible-automation-platform/gateway/settings.py')
load_python_file_with_injected_context(settings_file_path, settings=DYNACONF)

load_standard_settings_files(DYNACONF)  # /etc/ansible-automation-platform/*.yaml

load_custom_envvars(DYNACONF)  # load custom unprefixed envvars
load_envvars(DYNACONF)  # load envvars prefixed with GATEWAY_
set_secret_key(DYNACONF)  # set secret key based on secret key file

# toggle feature flags, considering flags coming from
# /etc/ansible-automation-platform/*.yaml
# and envvars like `GATEWAY_FEATURE_FOO_ENABLED=true
DYNACONF.update(
    toggle_feature_flags(DYNACONF),
    loader_identifier="settings:toggle_feature_flags",
    merge=True,
)

export(__name__, DYNACONF)  # export back to django.conf.settings
