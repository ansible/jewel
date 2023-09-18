from django.apps import AppConfig
from django.db.models import signals
from dynamic_preferences.signals import preference_updated


def _initialize_preferences(sender, **kwargs):
    from aap_gateway_api.utils.preferences import initialize_preferences

    initialize_preferences()


def _notify_on_preference_update(sender, section, name, old_value, new_value, **kwargs):
    '''
    This signal gets called when a preference is updated. We use it to call the on_update
    method of the preference if it exists. This means we don't have to hardcode preference
    names and sections here in the signal handler.
    '''
    from aap_gateway_api.models import gateway_preference_registry

    preference = gateway_preference_registry.get(name, section)
    if preference.on_update:
        preference.on_update(old_value, new_value)


class MyAppConfig(AppConfig):
    name = 'aap_gateway_api'
    verbose_name = "Gateway"

    def ready(self):
        signals.post_migrate.connect(_initialize_preferences, sender=self, weak=False)
        preference_updated.connect(_notify_on_preference_update)
