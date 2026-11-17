from copy import deepcopy

import psycopg
import pytest
from django.conf import settings as django_settings
from django.db import connection
from django.test import override_settings

from aap_gateway_api.dispatch.config import get_dispatcherd_config


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
def test_config_structure():
    config = get_dispatcherd_config()
    assert config["version"] == 2
    assert "service" in config
    assert "brokers" in config
    assert "producers" in config
    assert "publish" in config
    assert config["publish"] == {"default_broker": "pg_notify"}
    assert config["producers"] == {}


def test_config_is_disabled_for_mssql():
    databases = deepcopy(django_settings.DATABASES)
    databases["default"].update(
        {
            "ENGINE": "ansible_base.backends.mssql",
            "NAME": "gateway",
            "USER": "sa",
            "PASSWORD": "YourStrong!Passw0rd",
            "HOST": "mssql",
            "PORT": 1433,
            "TIME_ZONE": None,
            "OPTIONS": {"driver": "ODBC Driver 18 for SQL Server"},
        }
    )

    with override_settings(DATABASES=databases):
        assert get_dispatcherd_config() is None


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
def test_config_service_settings():
    config = get_dispatcherd_config()
    service = config["service"]
    assert service["process_manager_cls"] == "ForkServerManager"
    assert "aap_gateway_api.dispatch.pre_fork" in service["process_manager_kwargs"]["preload_modules"]
    assert service["min_workers"] == 2
    assert service["max_workers"] == 4


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
def test_config_broker_settings():
    config = get_dispatcherd_config()
    broker = config["brokers"]["pg_notify"]
    assert "conninfo" in broker["config"]
    assert broker["sync_connection_factory"] == "ansible_base.lib.utils.db.psycopg_connection_from_django"
    assert broker["default_publish_channel"] == "gateway_broadcast"
    assert "gateway_broadcast" in broker["channels"]


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
@override_settings(CLUSTER_HOST_ID="test-node-1")
def test_config_uses_cluster_host_id():
    config = get_dispatcherd_config()
    channels = config["brokers"]["pg_notify"]["channels"]
    assert "test-node-1" in channels
    assert "gateway_broadcast" in channels


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
@override_settings(DISPATCHERD_MIN_WORKERS=1, DISPATCHERD_MAX_WORKERS=8)
def test_config_worker_settings_override():
    config = get_dispatcherd_config()
    assert config["service"]["min_workers"] == 1
    assert config["service"]["max_workers"] == 8


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "microsoft", reason="SQL Server dispatcherd support is not ready")
def test_conninfo_is_parseable():
    """The generated conninfo string must be parseable by psycopg."""
    config = get_dispatcherd_config()
    conninfo = config["brokers"]["pg_notify"]["config"]["conninfo"]
    parsed = psycopg.conninfo.conninfo_to_dict(conninfo)
    assert "dbname" in parsed
