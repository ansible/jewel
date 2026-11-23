from copy import deepcopy

import psycopg
import pytest
from django.conf import settings as django_settings
from django.db import connection
from django.test import override_settings

from aap_gateway_api.dispatch.config import get_dispatcherd_config, pyodbc_connection_from_config


def _default_broker_name():
    return "sqlserver" if connection.vendor == "microsoft" else "pg_notify"


@pytest.mark.django_db
def test_config_structure():
    config = get_dispatcherd_config()
    assert config["version"] == 2
    assert "service" in config
    assert "brokers" in config
    assert "producers" in config
    assert "publish" in config
    assert config["publish"] == {"default_broker": _default_broker_name()}
    assert config["producers"] == {}


def test_config_broker_names_resolve_to_modules():
    """dispatcherd resolves broker dict keys as module names under dispatcherd.brokers."""
    import importlib

    from dispatcherd.brokers import _resolve_module_name

    config = get_dispatcherd_config()
    for name in config["brokers"]:
        importlib.import_module(_resolve_module_name(name))


def test_config_selects_sql_server_broker():
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
        config = get_dispatcherd_config()

    broker = config["brokers"]["sqlserver"]
    assert "pg_notify" not in config["brokers"]
    assert config["publish"]["default_broker"] == "sqlserver"
    assert broker["channels"] == [getattr(django_settings, "CLUSTER_HOST_ID", "gateway"), "gateway_broadcast"]
    assert broker["default_publish_channel"] == "gateway_broadcast"
    assert broker["sync_connection_factory"] == "aap_gateway_api.dispatch.config.pyodbc_connection_from_config"
    conn_string = broker["config"]["connection_string"]
    assert "SERVER=mssql,1433" in conn_string
    assert "DATABASE=gateway" in conn_string
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_string


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
    broker = config["brokers"][_default_broker_name()]
    if connection.vendor == "microsoft":
        assert "connection_string" in broker["config"]
        assert broker["sync_connection_factory"] == "aap_gateway_api.dispatch.config.pyodbc_connection_from_config"
    else:
        assert "conninfo" in broker["config"]
        assert broker["sync_connection_factory"] == "ansible_base.lib.utils.db.psycopg_connection_from_django"
    assert broker["default_publish_channel"] == "gateway_broadcast"
    assert "gateway_broadcast" in broker["channels"]


@pytest.mark.django_db
@override_settings(CLUSTER_HOST_ID="test-node-1")
def test_config_uses_cluster_host_id():
    config = get_dispatcherd_config()
    channels = config["brokers"][_default_broker_name()]["channels"]
    assert "test-node-1" in channels
    assert "gateway_broadcast" in channels


@pytest.mark.django_db
@override_settings(DISPATCHERD_MIN_WORKERS=1, DISPATCHERD_MAX_WORKERS=8)
def test_config_worker_settings_override():
    config = get_dispatcherd_config()
    assert config["service"]["min_workers"] == 1
    assert config["service"]["max_workers"] == 8


@pytest.mark.django_db
def test_conninfo_is_parseable():
    """The generated broker connection info must be parseable by its client library."""
    config = get_dispatcherd_config()
    if connection.vendor == "microsoft":
        conn_string = config["brokers"]["sqlserver"]["config"]["connection_string"]
        assert conn_string.count(";") >= 4  # SERVER, DATABASE, UID, PWD, DRIVER
        assert all("=" in part for part in conn_string.split(";") if part)
    else:
        conninfo = config["brokers"]["pg_notify"]["config"]["conninfo"]
        parsed = psycopg.conninfo.conninfo_to_dict(conninfo)
        assert "dbname" in parsed


def test_pyodbc_connection_from_config_returns_django_connection(monkeypatch):
    """The sync publish factory returns Django's underlying connection, not a new one."""
    try:
        import pyodbc
    except ImportError:
        # Not installed, or installed without unixODBC (PostgreSQL runners get
        # pyodbc via DAB's dependency set but cannot import it).
        pytest.skip("pyodbc is not importable in this environment")

    class FakeConnection:
        pass

    class FakeDatabase:
        vendor = "microsoft"

        def __init__(self):
            self.connection = FakeConnection()

        def validate_thread_sharing(self):
            pass

        def ensure_connection(self):
            pass

        def validate_no_broken_transaction(self):
            pass

    # The factory lazy-imports pyodbc, so patch the class it checks against.
    monkeypatch.setattr(pyodbc, "Connection", FakeConnection)
    fake = FakeDatabase()
    monkeypatch.setattr("aap_gateway_api.dispatch.config.connections", {"default": fake})
    assert pyodbc_connection_from_config(connection_string="ignored=too") is fake.connection


def test_pyodbc_connection_from_config_rejects_wrong_backend(monkeypatch):
    """A non-pyodbc Django connection is rejected rather than silently misused."""

    class FakeDatabase:
        vendor = "microsoft"
        connection = object()

        def validate_thread_sharing(self):
            pass

        def ensure_connection(self):
            pass

        def validate_no_broken_transaction(self):
            pass

    monkeypatch.setattr("aap_gateway_api.dispatch.config.connections", {"default": FakeDatabase()})
    with pytest.raises(TypeError, match="pyodbc driver"):
        pyodbc_connection_from_config()
