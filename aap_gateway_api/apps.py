from django.apps import AppConfig
from django.db.models import signals


def _initialize_preferences(sender, **kwargs):
    from aap_gateway_api.utils.preferences import initialize_preferences

    initialize_preferences()


class MyAppConfig(AppConfig):
    name = 'aap_gateway_api'
    verbose_name = "Gateway"

    def ready(self):
        signals.post_migrate.connect(_initialize_preferences, sender=self, weak=False)
