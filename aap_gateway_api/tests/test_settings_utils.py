import sys
from os import environ
from unittest.mock import patch

import pytest
from ansible_base.lib.dynamic_config import factory

from aap_gateway_api.settings_utils import _CUSTOM_ENVVAR_MAPPINGS, load_custom_envvars, load_grpc_settings, load_oidc_provider_settings


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


class TestLoadCustomEnvvars:
    """Tests for load_custom_envvars and the _CUSTOM_ENVVAR_MAPPINGS table."""

    @pytest.fixture
    def dynaconf_settings(self):
        return factory(
            __name__,
            "GATEWAY_TEST",
            settings_files=["defaults.py", "settings_dev.py"],
        )

    def test_direct_passthrough_envvars(self, dynaconf_settings):
        """Test that direct passthrough env vars are mapped to the correct settings keys."""
        env_overrides = {
            "DATABASE_ENGINE": "django.db.backends.postgresql",
            "DATABASE_NAME": "testdb",
            "DATABASE_USER": "testuser",
            "DATABASE_PASSWORD": "testpass",
            "DATABASE_HOST": "db.example.com",
            "DATABASE_PORT": "5433",
            "ENVOY_HOSTNAME": "envoy.example.com",
            "GATEWAY_CERT_FILE": "/etc/ssl/cert.pem",
            "GATEWAY_KEY_FILE": "/etc/ssl/key.pem",
            "REDIS_URL": "redis://redis.example.com:6379/0",
            "CACHE_KEY_PREFIX": "test_prefix",
            "REDIS_MODE": "sentinel",
        }
        with patch.dict(environ, env_overrides, clear=False):
            load_custom_envvars(dynaconf_settings)

        assert dynaconf_settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
        assert dynaconf_settings.DATABASES["default"]["NAME"] == "testdb"
        assert dynaconf_settings.DATABASES["default"]["USER"] == "testuser"
        assert dynaconf_settings.DATABASES["default"]["PASSWORD"] == "testpass"
        assert dynaconf_settings.DATABASES["default"]["HOST"] == "db.example.com"
        assert dynaconf_settings.DATABASES["default"]["PORT"] == "5433"
        assert dynaconf_settings.ENVOY_HOSTNAME == "envoy.example.com"
        assert dynaconf_settings.GATEWAY_CERT_FILE == "/etc/ssl/cert.pem"
        assert dynaconf_settings.GATEWAY_KEY_FILE == "/etc/ssl/key.pem"
        assert dynaconf_settings.CACHES["primary"]["LOCATION"] == "redis://redis.example.com:6379/0"
        assert dynaconf_settings.CACHES["primary"]["KEY_PREFIX"] == "test_prefix"
        assert dynaconf_settings.CACHES["primary"]["OPTIONS"]["CLIENT_CLASS_KWARGS"]["mode"] == "sentinel"

    def test_boolean_transform_envvars(self, dynaconf_settings):
        """Test that boolean-transformed env vars are converted via to_python_boolean."""
        env_overrides = {
            "REDIS_TLS": "true",
            "PING_PAGE_CHECK_IGNORE_CERT": "false",
        }
        with patch.dict(environ, env_overrides, clear=False):
            load_custom_envvars(dynaconf_settings)

        assert dynaconf_settings.CACHES["primary"]["OPTIONS"]["CLIENT_CLASS_KWARGS"]["ssl"] is True
        assert dynaconf_settings.PING_PAGE_CHECK_IGNORE_CERT is False

    def test_comma_split_transform_envvar(self, dynaconf_settings):
        """Test that LOGOUT_ALLOWED_HOSTS is split on commas."""
        with patch.dict(environ, {"LOGOUT_ALLOWED_HOSTS": "host1.example.com,host2.example.com,host3.example.com"}, clear=False):
            load_custom_envvars(dynaconf_settings)

        assert dynaconf_settings.LOGOUT_ALLOWED_HOSTS == ["host1.example.com", "host2.example.com", "host3.example.com"]

    def test_unset_envvars_do_not_override_defaults(self, dynaconf_settings):
        """Test that unset env vars do not produce entries that override defaults."""
        original_hostname = dynaconf_settings.ENVOY_HOSTNAME

        # Ensure the env var is not set
        env_to_clear = [entry[0] for entry in _CUSTOM_ENVVAR_MAPPINGS]
        with patch.dict(environ, {}, clear=False):
            for var in env_to_clear:
                environ.pop(var, None)
            load_custom_envvars(dynaconf_settings)

        # ENVOY_HOSTNAME should retain its default value
        assert dynaconf_settings.ENVOY_HOSTNAME == original_hostname

    def test_grpc_min_value_override(self, dynaconf_settings):
        """Test that GRPC message length is overridden when set below minimum."""
        min_value = dynaconf_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE
        below_min = str(min_value - 1)

        with patch.dict(environ, {"GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH": below_min}, clear=False):
            # First apply the env var so it gets set on settings
            dynaconf_settings.set("GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH", int(below_min))
            load_custom_envvars(dynaconf_settings)

        assert dynaconf_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH == min_value

    def test_grpc_min_value_stderr_message(self, dynaconf_settings, capsys):
        """Test that a warning is written to stderr when GRPC value is below minimum."""
        min_value = dynaconf_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE
        below_min = str(min_value - 1)

        with patch.dict(environ, {"GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH": below_min}, clear=False):
            dynaconf_settings.set("GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH", int(below_min))
            load_custom_envvars(dynaconf_settings)

        captured = capsys.readouterr()
        assert "GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH was set lower than allowed minimum" in captured.err

    def test_grpc_above_min_not_overridden(self, dynaconf_settings):
        """Test that GRPC message length is NOT overridden when at or above minimum."""
        min_value = dynaconf_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE
        above_min = str(min_value + 100)

        with patch.dict(environ, {"GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH": above_min}, clear=False):
            dynaconf_settings.set("GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH", int(above_min))
            load_custom_envvars(dynaconf_settings)

        # The env var value is applied as a string (env vars are always strings);
        # the GRPC override does not trigger since the pre-set int value is above minimum
        assert dynaconf_settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH == above_min

    def test_mapping_table_completeness(self):
        """Verify the mapping table has the expected number of entries."""
        assert len(_CUSTOM_ENVVAR_MAPPINGS) == 27

    def test_mapping_table_entry_structure(self):
        """Verify all mapping entries have valid structure (2 or 3 elements)."""
        for entry in _CUSTOM_ENVVAR_MAPPINGS:
            assert len(entry) in (2, 3), f"Entry {entry[0]} has unexpected length {len(entry)}"
            assert isinstance(entry[0], str), f"Entry {entry[0]}: env var name must be a string"
            assert isinstance(entry[1], str), f"Entry {entry[0]}: setting key must be a string"
            if len(entry) == 3:
                assert callable(entry[2]), f"Entry {entry[0]}: transform must be callable"
