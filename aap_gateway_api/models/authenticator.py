from django.db.models import JSONField, fields

from aap_gateway_api.models.common import NamedCommonModel


class Authenticator(NamedCommonModel):
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects in Gateway (users, teams, organizations)")
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
