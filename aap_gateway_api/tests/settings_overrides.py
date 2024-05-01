from fakeredis import FakeConnection

from aap_gateway_api.settings import *  # noqa: F403

# noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "aap_gateway_api/tests/db.sqlite3",
        "TEST": {
            "NAME": "aap_gateway_api/tests/db_test.sqlite3",
        },
    }
}

# Mock the redis cache with fakeredis
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://localhost:6379",
        "OPTIONS": {
            "connection_class": FakeConnection,
        },
    }
}

for logger in LOGGING["loggers"]:  # noqa: F405
    LOGGING["loggers"][logger]["level"] = "ERROR"  # noqa: F405

# Caching breaks unit tests because:
#   1. we don't have anything that will clear the cache on a per-test basis
#   2. even if we did, we have tests running in parallel so we would need each thread to have its own cache
# Neither are insurmountable but we haven't solved it
DYNAMIC_PREFERENCES['ENABLE_CACHE'] = False  # noqa: F405
