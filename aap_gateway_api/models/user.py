import logging

from crum import get_current_user
from django.contrib.auth.hashers import is_password_usable, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.timezone import now

logger = logging.getLogger('aap.gateway.models.user')


class User(AbstractUser):
    # Its too bad we can't extend NamedCommonModel but it would have FKs to ourselves which is not possible.
    # So instead we are going to add these fields but use the definition of AbstractUser.username instead of a FK
    # This will end up being just text but :shrug:
    created_on = models.DateTimeField(
        default=None,
        editable=False,
    )
    created_by = AbstractUser.username
    modified_on = models.DateTimeField(
        default=None,
        editable=False,
    )
    modified_by = AbstractUser.username
    is_system_auditor = models.BooleanField(default=False, null=False)
    claims = models.JSONField(default=dict, null=False)
    last_login_map_results = models.JSONField(default=list, null=False)
    # This field tracks if a user passed or failed an allow map
    access_allowed = models.BooleanField(default=None, null=True)

    reverse_foreign_key_fields = ['teams']

    def save(self, *args, **kwargs):
        update_fields = list(kwargs.get('update_fields', []))
        user = get_current_user()
        # Manually perform auto_now_add and auto_now logic.
        if not self.pk and not self.created_on:
            self.created_on = now()
            self.created_by = user.username if user else 'System'
            if 'created_on' not in update_fields:
                update_fields.append('created_on')
            if 'created_by' not in update_fields:
                update_fields.append('created_by')
        if 'modified_on' not in update_fields or not self.modified_on:
            self.modified_on = now()
            self.modified_by = user.username if user else 'System'
            update_fields.append('modified_on')
            update_fields.append('modified_by')

        # If the password is not already encrypted we need to do that.
        # If we ever change the algorithm for the password encryption this might break
        # The is_password_usable check will prevent us from overwriting an unusable password from an external account
        if is_password_usable(self.password) and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)

        super().save(*args, **kwargs)

    def logout(self):
        logger.debug(f"Logging out user {self.username} from any active backends")
        # cookies = Cookie.objects.filter(user=self)
        # for cookie in cookies:
        #    cookie.logout()

    # This is how we want this object built in summary_fields for other objects.
    def summary_fields(self):
        return {
            'id': self.id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
        }
