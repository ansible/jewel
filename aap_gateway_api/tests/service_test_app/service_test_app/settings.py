from ansible_base.lib.dynamic_config import export, factory, load_envvars, load_standard_settings_files

DYNACONF = factory(
    __name__,
    "SERVICE_TEST_APP",
    # Options passed directly to dynaconf
    settings_files=["defaults.py"],
)
load_standard_settings_files(DYNACONF)  # /etc/ansible-automation-platform/*.yaml
load_envvars(DYNACONF)  # load envvars prefixed with MYAPP_

export(__name__, DYNACONF)  # export back to django.conf.settings
