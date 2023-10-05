from django.db.models import JSONField, fields

from aap_gateway_api.models.common import NamedCommonModel


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
        max_length=1,
        choices=[
            ('l', 'ldap'),
        ],
        help_text="The type of authentication service this is",
    )

    reverse_foreign_key_fields = ['authenticator-map']

    def save(self, *args, **kwargs):
        from aap_gateway_api.utils import gateway_encryption

        if self.type == 'l':
            from aap_gateway_api.authentication.ldap import configuration_encrypted_fields

            for field in configuration_encrypted_fields:
                if field in self.configuration:
                    self.configuration[field] = gateway_encryption.encrypt_string(self.configuration[field])

        super().save(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values):
        from aap_gateway_api.utils import ENCRYPTED_STRING, gateway_encryption

        instance = super().from_db(db, field_names, values)
        if instance.type == 'l':
            from aap_gateway_api.authentication.ldap import configuration_encrypted_fields

            for field in configuration_encrypted_fields:
                if field in instance.configuration and instance.configuration[field].startswith(ENCRYPTED_STRING):
                    instance.configuration[field] = gateway_encryption.decrypt_string(instance.configuration[field])

        return instance
