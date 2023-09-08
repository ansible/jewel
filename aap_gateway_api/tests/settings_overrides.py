from aap_gateway_api.settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "tests/db.sqlite3",
        "TEST": {
            "NAME": "tests/db_test.sqlite3",
        },
    }
}

for logger in LOGGING["loggers"]:
    LOGGING["loggers"][logger]["level"] = "ERROR"
