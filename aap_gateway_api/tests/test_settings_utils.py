import sys
from os import environ
from unittest.mock import patch

import pytest
from ansible_base.lib.dynamic_config import factory

from aap_gateway_api.settings_utils import load_grpc_settings


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
