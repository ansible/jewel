import os

from fakeredis import FakeConnection

from aap_gateway_api.settings import *  # noqa: F403

# noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("ANSIBLE_GW_TEST_DB_HOST", "localhost"),
        # These are defined in tools/dev_postgres/Dockerfile and in pyproject.toml (tox config)
        "NAME": "gw_db",
        "USER": "gw",
        "PASSWORD": "password",
        "PORT": os.getenv("DB_PORT", 5432),
        "OPTIONS": {
            "keepalives_count": 5,
        },
    }
}

# Mock the redis cache with fakeredis and worker isolation
CACHES = {
    "default": {
        "BACKEND": "aap_gateway_api.tests.cache_backends.WorkerIsolatedRedisCache",
        "LOCATION": "redis://localhost:6379",
        "OPTIONS": {
            "connection_class": FakeConnection,
        },
    }
}

for logger in LOGGING["loggers"]:  # noqa: F405
    LOGGING["loggers"][logger]["level"] = "ERROR"  # noqa: F405

# Caching is now supported in tests with proper worker isolation via WorkerIsolatedRedisCache
# Each pytest-xdist worker gets its own cache prefix, and cache.clear() only clears that worker's keys
DYNAMIC_PREFERENCES['ENABLE_CACHE'] = True  # noqa: F405
