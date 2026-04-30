from django.conf import settings


def _get_conninfo():
    db = settings.DATABASES["default"]
    db_options = db.get("OPTIONS", {})
    return (
        f"host={db.get('HOST', 'localhost')} "
        f"port={db.get('PORT', 5432)} "
        f"dbname={db.get('NAME', '')} "
        f"user={db.get('USER', '')} "
        f"password={db.get('PASSWORD', '')} "
        f"sslmode={db_options.get('sslmode', 'allow')} "
        f"sslcert={db_options.get('sslcert', '')} "
        f"sslkey={db_options.get('sslkey', '')} "
        f"sslrootcert={db_options.get('sslrootcert', '')}"
    )


def get_dispatcherd_config():
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
        "brokers": {
            "pg_notify": {
                "config": {
                    "conninfo": _get_conninfo(),
                },
                "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
                "max_connection_idle_seconds": None,
                "channels": [
                    getattr(settings, "CLUSTER_HOST_ID", "gateway"),
                    "gateway_broadcast",
                ],
                "default_publish_channel": "gateway_broadcast",
            }
        },
        "producers": {},
        "publish": {"default_broker": "pg_notify"},
    }
