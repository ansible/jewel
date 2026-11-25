# Backend-specific database OPTIONS for the gRPC server's connections.
# Applied (with explicit configuration taking precedence) after every settings
# source that can select the database engine has loaded; engines without an
# entry get no backend-specific defaults.
GRPC_DATABASE_OPTIONS = {
    "django.db.backends.postgresql": {
        "keepalives": 1,
        "keepalives_idle": 5,
        "keepalives_interval": 5,
        "keepalives_count": 5,
        "application_name": "GRPC Server",
    },
    "ansible_base.backends.mssql": {
        "APP": "GRPC Server",
    },
}
