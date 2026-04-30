from unittest import mock

import pytest

from aap_gateway_api.dispatch.config import get_dispatcherd_config


@pytest.mark.django_db
def test_config_structure():
    config = get_dispatcherd_config()
    assert config["version"] == 2
    assert "service" in config
    assert "brokers" in config
    assert "producers" in config
    assert "publish" in config
    assert config["publish"] == {"default_broker": "pg_notify"}
    assert config["producers"] == {}


@pytest.mark.django_db
def test_config_service_settings():
    config = get_dispatcherd_config()
    service = config["service"]
    assert service["process_manager_cls"] == "ForkServerManager"
    assert "aap_gateway_api.dispatch.pre_fork" in service["process_manager_kwargs"]["preload_modules"]
    assert service["min_workers"] == 2
    assert service["max_workers"] == 4


@pytest.mark.django_db
def test_config_broker_settings():
    config = get_dispatcherd_config()
    broker = config["brokers"]["pg_notify"]
    assert "conninfo" in broker["config"]
    assert broker["sync_connection_factory"] == "ansible_base.lib.utils.db.psycopg_connection_from_django"
    assert broker["default_publish_channel"] == "gateway_broadcast"
    assert "gateway_broadcast" in broker["channels"]


@pytest.mark.django_db
def test_config_uses_cluster_host_id():
    with mock.patch("aap_gateway_api.dispatch.config.settings") as mock_settings:
        mock_settings.CLUSTER_HOST_ID = "test-node-1"
        mock_settings.DISPATCHERD_MIN_WORKERS = 2
        mock_settings.DISPATCHERD_MAX_WORKERS = 4
        mock_settings.DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "test",
                "USER": "test",
                "PASSWORD": "test",
                "HOST": "localhost",
                "PORT": 5432,
                "OPTIONS": {},
            }
        }

        config = get_dispatcherd_config()
        channels = config["brokers"]["pg_notify"]["channels"]
        assert "test-node-1" in channels
        assert "gateway_broadcast" in channels


@pytest.mark.django_db
def test_config_worker_settings_override():
    with mock.patch("aap_gateway_api.dispatch.config.settings") as mock_settings:
        mock_settings.DISPATCHERD_MIN_WORKERS = 1
        mock_settings.DISPATCHERD_MAX_WORKERS = 8
        mock_settings.CLUSTER_HOST_ID = "node"
        mock_settings.DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "test",
                "USER": "test",
                "PASSWORD": "test",
                "HOST": "localhost",
                "PORT": 5432,
                "OPTIONS": {},
            }
        }

        config = get_dispatcherd_config()
        assert config["service"]["min_workers"] == 1
        assert config["service"]["max_workers"] == 8
