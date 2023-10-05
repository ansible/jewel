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
        from ansible_base.utils.encryption import ansible_encryption

        if self.preference.encrypted:
            self.value = ansible_encryption.encrypt_string(self.value)
        super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        from ansible_base.utils.encryption import ENCRYPTED_STRING, ansible_encryption

        instance = super().from_db(db, field_names, values)
        # We don't want to check the instance.preference.encrypted here because we could have a Fallback
        # A fall back happens when there is a value in DB but not a corresponding register
        if type(instance.value) is str and instance.value.startswith(ENCRYPTED_STRING):
            instance.value = ansible_encryption.decrypt_string(instance.value)
        return instance


gateway_preference_registry.preference_model = Preference

# Register the Preference model with our registry (seems redundant but :shrug:)
preference_models.register(Preference, gateway_preference_registry)
