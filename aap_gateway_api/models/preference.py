import logging

from dynamic_preferences import models
from dynamic_preferences.registries import GlobalPreferenceRegistry, preference_models

logger = logging.getLogger('aap.gateway.models.preference')


class PreferenceRegistry(GlobalPreferenceRegistry):
    pass


gateway_preference_registry = PreferenceRegistry()


class Preference(models.BasePreferenceModel):
    registry = gateway_preference_registry

    class Meta:
        app_label = "aap_gateway_api"
        unique_together = ("section", "name")

    def save(self, *args, **kwargs):
        from aap_gateway_api.utils import gateway_encryption

        if self.preference.encrypted:
            self.value = gateway_encryption.encrypt_string(self.value)
        super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        from aap_gateway_api.utils import gateway_encryption

        instance = super().from_db(db, field_names, values)
        if instance.preference.encrypted:
            instance.value = gateway_encryption.decrypt_string(instance.value)
        return instance


gateway_preference_registry.preference_model = Preference

# Register the Preference model with our registry (seems redundant but :shrug:)
preference_models.register(Preference, gateway_preference_registry)
