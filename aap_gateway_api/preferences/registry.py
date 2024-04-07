from dynamic_preferences.registries import GlobalPreferenceRegistry, preference_models

from aap_gateway_api.models import Preference

from .encrypted_manager import EncryptedPreferencesManager


class PreferenceRegistry(GlobalPreferenceRegistry):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.preference_model = Preference

    def manager(self, **kwargs):
        """Return a preference manager that can be used to retrieve preference values"""
        return EncryptedPreferencesManager(registry=self, model=Preference, **kwargs)


gateway_preference_registry = PreferenceRegistry()

# Register the Preference model with our registry (seems redundant but :shrug:)
preference_models.register(Preference, gateway_preference_registry)
