import logging

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.models import user_summary_fields
from django.contrib.auth.hashers import is_password_usable, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models

logger = logging.getLogger('aap.gateway.models.user')


class User(AbstractUser, CommonModel):
    ignore_relations = [
        'authenticator_user',  # private model
        'groups',  # not using the auth app stuff, see Team model
        'user_permissions',  # not using auth app permissions
        'logentry',  # used for Django admin pages, not the API
    ]
    is_system_auditor = models.BooleanField(default=False, null=False)

    encrypted_fields = ()  # handed as special case by UserSerializer

    def save(self, *args, **kwargs):
        if is_password_usable(self.password) and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)

        super().save(*args, **kwargs)

    def logout(self):
        logger.debug(f"Logging out user {self.username} from any active backends")
        # cookies = Cookie.objects.filter(user=self)
        # for cookie in cookies:
        #    cookie.logout()

    def summary_fields(self):
        return user_summary_fields(self)
