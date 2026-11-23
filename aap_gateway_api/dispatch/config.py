from typing import TYPE_CHECKING

from ansible_base.lib.mssql.notify import get_sql_server_notify_conn_string
from ansible_base.lib.utils.db import psycopg_conn_string_from_settings_dict
from django.conf import settings
from django.db import connections

if TYPE_CHECKING:
    import pyodbc

MSSQL_ENGINE = "ansible_base.backends.mssql"


def pyodbc_connection_from_config(using: str = "default", **kwargs) -> "pyodbc.Connection":
    """Return Django's underlying pyodbc connection for dispatcherd sql_server publishing.

    The sql_server broker calls its sync_connection_factory with the broker
    config as kwargs, which are intentionally ignored: Django owns this
    connection's credentials, autocommit, timeout and transaction state. This
    mirrors dispatcherd's documented Django publishing pattern and matches the
    PostgreSQL broker's factory (which also returns Django's live connection):
    a message published inside a Django transaction is delivered on commit,
    and a rollback retracts it, instead of being sent immediately on a
    separate autocommit connection.

    ``pyodbc`` is imported here, not at module scope, so PostgreSQL-only
    environments (no unixODBC) can load the dispatch config without it.
    """
    import pyodbc

    database = connections[using]
    database.validate_thread_sharing()
    database.ensure_connection()
    database.validate_no_broken_transaction()
    if database.vendor != "microsoft" or not isinstance(database.connection, pyodbc.Connection):
        raise TypeError("sql_server publishing requires mssql-django with its pyodbc driver")
    return database.connection


def get_dispatcherd_config() -> dict:
    channels = [
        getattr(settings, "CLUSTER_HOST_ID", "gateway"),
        "gateway_broadcast",
    ]

    if settings.DATABASES["default"]["ENGINE"] == MSSQL_ENGINE:
        # The broker dict key is the module name under dispatcherd.brokers
        # (like pg_notify), so it must match the sqlserver module exactly.
        brokers = {
            "sqlserver": {
                "config": {
                    "connection_string": get_sql_server_notify_conn_string(),
                },
                "sync_connection_factory": "aap_gateway_api.dispatch.config.pyodbc_connection_from_config",
                "channels": channels,
                "default_publish_channel": "gateway_broadcast",
            }
        }
        default_broker = "sqlserver"
    else:
        brokers = {
            "pg_notify": {
                "config": {
                    "conninfo": psycopg_conn_string_from_settings_dict(settings.DATABASES["default"]),
                },
                "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
                "channels": channels,
                "default_publish_channel": "gateway_broadcast",
            }
        }
        default_broker = "pg_notify"

    return {
        "version": 2,
        "service": {
            "process_manager_cls": "ForkServerManager",
            "process_manager_kwargs": {
                "preload_modules": ["aap_gateway_api.dispatch.pre_fork"],
            },
            "min_workers": getattr(settings, "DISPATCHERD_MIN_WORKERS", 2),
            "max_workers": getattr(settings, "DISPATCHERD_MAX_WORKERS", 4),
        },
        "brokers": brokers,
        "producers": {},
        "publish": {"default_broker": default_broker},
    }
