from aap_gateway_api.settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "aap_gateway_api/tests/db.sqlite3",
        "TEST": {
            "NAME": "aap_gateway_api/tests/db_test.sqlite3",
        },
    }
}

for logger in LOGGING["loggers"]:
    LOGGING["loggers"][logger]["level"] = "ERROR"
