import sys
from os import environ
from unittest.mock import patch

import pytest
from ansible_base.lib.dynamic_config import factory

from aap_gateway_api.settings_utils import load_grpc_settings, load_oidc_provider_settings


@pytest.mark.parametrize(
    "test_args,log_message,keepalives_count",
    [
        (["start_grpc_server"], "Loading GRPC settings", 75),
        (["not_the_grpc_server"], "Not starting GRPC server, skipped loading GRPC settings", 5),
    ],
)
def test_load_grpc_settings_displays_proper_message(test_args, log_message, keepalives_count, expected_log):
    DYNACONF = factory(
        __name__,
        "GATEWAY_TEST",
        # Options passed directly to dynaconf
        settings_files=["defaults.py", "settings_dev.py"],
    )

    with expected_log(
        'aap_gateway_api.settings_utils.logger',
        'debug',
        log_message,
    ):
        with patch.object(sys, 'argv', test_args):
            load_grpc_settings(DYNACONF)
            assert DYNACONF.DATABASES['default']['OPTIONS'].get('keepalives_count', 5) == keepalives_count


def test_validate_grpc_settings_in_etc_aap_gw_override(tmp_path_factory, expected_log):
    expected_settings = 475

    # Create a temp grpc_settings.py and populate it with our expected value
    temp_dir = tmp_path_factory.mktemp("grpc_settings_dir")
    temp_settings = f"{temp_dir}/grpc_settings.py"
    with open(temp_settings, 'w') as f:
        f.write(f"DATABASES__default__OPTIONS__keepalives_count={expected_settings}")
    environ['GATEWAY_GRPC_SETTINGS_FILE'] = temp_settings

    DYNACONF = factory(
        __name__,
        "GATEWAY_TEST",
        # Options passed directly to dynaconf
        settings_files=["defaults.py", "settings_dev.py"],
    )

    with expected_log(
        'aap_gateway_api.settings_utils.logger',
        'debug',
        'Loading GRPC settings',
    ):
        with patch.object(sys, 'argv', ['start_grpc_server']):
            load_grpc_settings(DYNACONF)
            assert DYNACONF.DATABASES['default']['OPTIONS'].get('keepalives_count', 0) == expected_settings


def test_load_oidc_provider_settings_enabled(expected_log):
    DYNACONF = factory(
        __name__,
        "GATEWAY_TEST",
        # Options passed directly to dynaconf
        settings_files=["defaults.py", "settings_dev.py"],
    )
    DYNACONF.set('FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED', True)

    with expected_log(
        'aap_gateway_api.settings_utils.logger',
        'debug',
        'Loading OIDC provider settings',
    ):
        load_oidc_provider_settings(DYNACONF)
        assert DYNACONF.get('OAUTH2_PROVIDER').get('OIDC_ENABLED')
        # Check class name instead of isinstance() because dynaconf loads the module
        # dynamically, creating a different class object than directly imported one
        private_key = DYNACONF.get('OAUTH2_PROVIDER').get('OIDC_RSA_PRIVATE_KEY')
        assert type(private_key).__name__ == 'LazyPrivateKey'


def test_load_oidc_provider_settings_disabled(expected_log):
    DYNACONF = factory(
        __name__,
        "GATEWAY_TEST",
        settings_files=["defaults.py", "settings_dev.py"],
    )
    # Don't set the feature flag, or explicitly set to False

    with expected_log(
        'aap_gateway_api.settings_utils.logger',
        'debug',
        'OIDC provider feature flag is disabled',
    ):
        load_oidc_provider_settings(DYNACONF)
        # Verify OIDC settings were NOT loaded
        oauth_provider = DYNACONF.get('OAUTH2_PROVIDER', {})
        assert oauth_provider.get('OIDC_ENABLED') is None
