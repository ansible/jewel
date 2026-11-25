# This file is copied here because dynaconf runs with a root of the tests folder
GRPC_DATABASE_OPTIONS = {
    "django.db.backends.postgresql": {
        "keepalives": 71,
        "keepalives_idle": 75,
        "keepalives_interval": 75,
        "keepalives_count": 75,
    },
    "ansible_base.backends.mssql": {
        "APP": "Django API",
    },
}
