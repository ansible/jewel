from ansible_base.lib.utils.encryption import ansible_encryption
from dynamic_preferences.registries import PreferencesManager
from dynamic_preferences.settings import preferences_settings


class EncryptedPreferencesManager(PreferencesManager):
    def to_cache(self, *prefs):
        """
        Update/create the cache value for the given preference model instances
        """
        update_dict = {}
        for pref in prefs:
            key = self.get_cache_key(pref.section, pref.name)
            value = pref.raw_value
            if pref.preference.encrypted:
                value = ansible_encryption.encrypt_string(value)
            if value is None or value == "":
                # some cache backends refuse to cache None or empty values
                # resulting in more DB queries, so we cache an arbitrary value
                # to ensure the cache is hot (even with empty values)
                value = preferences_settings.CACHE_NONE_VALUE
            update_dict[key] = value

        self.cache.set_many(update_dict)
