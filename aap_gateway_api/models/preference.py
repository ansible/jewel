import logging

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.utils.encryption import ansible_encryption
from cryptography.fernet import InvalidToken
from dynamic_preferences import models

logger = logging.getLogger('aap.gateway.models.preference')


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
        if isinstance(instance.value, str):
            was_encrypted = ansible_encryption.is_encrypted_string(instance.value)[0]
            try:
                instance.value = ansible_encryption.decrypt_string(instance.value)
            except InvalidToken:
                logger.critical(
                    "Failed to decrypt Preference(section=%r, name=%r): the SECRET_KEY may have changed. "
                    "Restore the original SECRET_KEY that encrypted this database, then restart. "
                    "Re-raising to prevent startup with corrupted preferences.",
                    instance.section,
                    instance.name,
                )
                raise
            if was_encrypted:
                instance._encrypted_field_names = {'raw_value'}
        return instance
