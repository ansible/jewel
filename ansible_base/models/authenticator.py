from django.db.models import JSONField, fields

from ansible_base.authentication.authenticators import get_authenticator_plugin

from .common import NamedCommonModel


class Authenticator(NamedCommonModel):
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects in Gateway (users, teams, organizations)")
    # TODO: Implement unique users, remove user, etc with team and org mapping feature.
    users_unique = fields.BooleanField(default=False, help_text="Are users from this source the same as users from another source with the same id")
    remove_users = fields.BooleanField(
        default=True, help_text="When a user authenticates from this source should they be removed from any other groups they were previously added to"
    )
    configuration = JSONField(default=dict, help_text="The required configuration for this source")
    type = fields.CharField(
        max_length=256,
        help_text="The type of authentication service this is",
    )
    order = fields.IntegerField(
        default=1, help_text="The order in which an authenticator will be tried. This only pertains to username/password authenticators"
    )

    reverse_foreign_key_fields = ['authenticator-map']

    def save(self, *args, **kwargs):
        from ansible_base.utils.encryption import ansible_encryption

        authenticator = get_authenticator_plugin(self.type)

        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in self.configuration:
                self.configuration[field] = ansible_encryption.encrypt_string(self.configuration[field])

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        from ansible_base.utils.encryption import ENCRYPTED_STRING, ansible_encryption

        instance = super().from_db(db, field_names, values)

        authenticator = get_authenticator_plugin(instance.type)
        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in instance.configuration and instance.configuration[field].startswith(ENCRYPTED_STRING):
                instance.configuration[field] = ansible_encryption.decrypt_string(instance.configuration[field])

        return instance
