from ansible_base.lib.utils.db import psycopg_conn_string_from_settings_dict
from django.conf import settings


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
                    "conninfo": psycopg_conn_string_from_settings_dict(settings.DATABASES["default"]),
                },
                "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
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
