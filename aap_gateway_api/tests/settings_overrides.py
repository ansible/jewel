from aap_gateway_api.settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "TEST": {
            "NAME": "tests/testdb.sqlite3",
        },
    }
}
