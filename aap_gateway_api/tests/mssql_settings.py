"""SQL Server test settings for the Gateway unit suite."""

import os

from aap_gateway_api.tests.settings_overrides import *  # noqa: F403

_MSSQL_PASSWORD = os.getenv("MSSQL_SA_PASSWORD", "YourStrong!Passw0rd")
_MSSQL_OPTIONS = {
    "driver": "ODBC Driver 18 for SQL Server",
    "extra_params": "Encrypt=yes;TrustServerCertificate=yes",
}

DATABASES = {
    "default": {
        "ENGINE": "ansible_base.backends.mssql",
        "HOST": os.getenv("ANSIBLE_GW_TEST_DB_HOST", "localhost"),
        "PORT": int(os.getenv("DB_PORT", "1433")),
        "NAME": "master",
        "USER": "sa",
        "PASSWORD": _MSSQL_PASSWORD,
        "OPTIONS": _MSSQL_OPTIONS,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "TEST": {"NAME": "test_gateway_mssql"},
    },
}

DATABASES["healthcheck"] = {
    **DATABASES["default"],
    "OPTIONS": {**_MSSQL_OPTIONS, "connection_timeout": 3},
    "CONN_MAX_AGE": 0,
    "TEST": {"MIRROR": "default"},
}

# This test profile exercises single-node SQL Server mode; Service Broker
# cache broadcasts are intentionally not part of the current integration.
ANSIBLE_BASE_REDIS_AUTO_INVALIDATE = False
