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

for logger in LOGGING["loggers"]:  # noqa: F405
    LOGGING["loggers"][logger]["level"] = "ERROR"  # noqa: F405

# Caching breaks unit tests.
DYNAMIC_PREFERENCES = {
    'REGISTRY_MODULE': 'preferences',
    'ENABLE_CACHE': False,
    'ENABLE_GLOBAL_MODEL_AUTO_REGISTRATION': False,
}
