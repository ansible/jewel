from ansible_base.lib.utils.encryption import ansible_encryption
from dynamic_preferences.exceptions import CachedValueNotFound
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

    def from_cache(self, section, name):
        """
        Return a preference raw_value from cache

        Note: This function is copied from the parent class because we have to account for the decryption of the value before the code tries to deserialize the
        value.
        """
        cached_value = self.cache.get(self.get_cache_key(section, name), CachedValueNotFound)

        if cached_value is CachedValueNotFound:
            raise CachedValueNotFound

        if cached_value == preferences_settings.CACHE_NONE_VALUE:
            cached_value = None
        else:
            cached_value = ansible_encryption.decrypt_string(cached_value)

        return self.registry.get(section=section, name=name).serializer.deserialize(cached_value)

    def many_from_cache(self, preferences):
        """
        Return cached value for given preferences
        missing preferences will be skipped

        Note: This function is copied from the parent class because we have to account for the decryption of the values before the code tries to deserialize
        the values.
        """
        keys = {p: self.get_cache_key(p.section.name, p.name) for p in preferences}
        cached = self.cache.get_many(list(keys.values()))

        for k, v in cached.items():
            # we replace dummy cached values by None here, if needed
            if v == preferences_settings.CACHE_NONE_VALUE:
                cached[k] = None
            else:
                cached[k] = ansible_encryption.decrypt_string(cached[k])

        # we have to remap returned value since the underlying cached keys
        # are not usable for an end user
        return {p.identifier(): p.serializer.deserialize(cached[k]) for p, k in keys.items() if k in cached}
