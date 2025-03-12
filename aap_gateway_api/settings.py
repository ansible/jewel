from ansible_base.lib.dynamic_config import export, factory, load_envvars, load_standard_settings_files, toggle_feature_flags

DYNACONF = factory(
    __name__,
    "GATEWAY",
    # Options passed directly to dynaconf
    environments=("development"),
    settings_files=["defaults.py"],
)

load_standard_settings_files(DYNACONF)  # /etc/ansible-automation-platform/*.yaml
load_envvars(DYNACONF)  # load envvars prefixed with MYAPP_

# toggle feature flags, considering flags coming from
# /etc/ansible-automation-platform/*.yaml
# and envvars like `GATEWAY_FEATURE_FOO_ENABLED=true
DYNACONF.update(
    toggle_feature_flags(DYNACONF),
    loader_identifier="settings:toggle_feature_flags",
    merge=True,
)

export(__name__, DYNACONF)  # export back to django.conf.settings
