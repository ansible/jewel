from typing import TYPE_CHECKING

from ansible_base.lib.mssql.notify import get_sql_server_notify_conn_string
from ansible_base.lib.utils.db import psycopg_conn_string_from_settings_dict
from django.conf import settings

if TYPE_CHECKING:
    import pyodbc

MSSQL_ENGINE = "ansible_base.backends.mssql"


def pyodbc_connection_from_config(**kwargs) -> "pyodbc.Connection":
    """Create a pyodbc connection from dispatcherd sql_server broker config kwargs.

    The sql_server broker calls its sync_connection_factory with the broker
    config as kwargs: the ``connection_string`` key selects the server and
    everything else passes to ``pyodbc.connect``. This mirrors the broker's
    own ``connect()`` — autocommit publishing and connection resiliency
    disabled so outages surface as errors instead of silent reconnects.

    ``pyodbc`` is imported here, not at module scope, so PostgreSQL-only
    environments (no unixODBC) can load the dispatch config without it.
    """
    import pyodbc

    options = dict(kwargs)
    connection_string = options.pop("connection_string")
    options.setdefault("autocommit", True)
    options.setdefault("timeout", 10)
    if "connectretrycount" not in connection_string.lower():
        connection_string += ";ConnectRetryCount=0"
    connection = pyodbc.connect(connection_string, **options)
    # pyodbc's `timeout` kwarg is only the login timeout; the query timeout
    # defaults to 0 (unbounded). Match the broker's connect(): a wedged
    # publish query must not hang the calling request indefinitely.
    connection.timeout = 35
    return connection


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
