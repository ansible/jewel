from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.utils.encryption import ansible_encryption
from dynamic_preferences import models


class Preference(models.BasePreferenceModel, AuditableModel):
    audit_log_enabled = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from aap_gateway_api.preferences import gateway_preference_registry

        self.registry = gateway_preference_registry

    class Meta:
        app_label = "aap_gateway_api"
        unique_together = ("section", "name")

    def save(self, *args, **kwargs):
        if self.preference.encrypted:
            self.value = ansible_encryption.encrypt_string(self.value)
            self._encrypted_field_names = {'raw_value'}
        super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # We don't want to check the instance.preference.encrypted here because we could have a Fallback
        # A fall back happens when there is a value in DB but not a corresponding register
        if type(instance.value) is str:
            was_encrypted = ansible_encryption.is_encrypted_string(instance.value)[0]
            instance.value = ansible_encryption.decrypt_string(instance.value)
            if was_encrypted:
                instance._encrypted_field_names = {'raw_value'}
        return instance
