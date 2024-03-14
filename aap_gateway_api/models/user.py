import logging

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.models import user_summary_fields
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.contrib.auth.hashers import get_hashers_by_algorithm, is_password_usable, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models

logger = logging.getLogger('aap.gateway.models.user')


def password_is_hashed(password):
    for algo in get_hashers_by_algorithm().keys():
        if password.startswith(algo):
            return True
    return False


class User(AbstractUser, CommonModel):
    ignore_relations = [
        'authenticator_user',  # private model
        'groups',  # not using the auth app stuff, see Team model
        'user_permissions',  # not using auth app permissions
        'logentry',  # used for Django admin pages, not the API
        'social_auth',  # Social auth endpoint
    ]
    is_system_auditor = models.BooleanField(default=False, null=False)

    encrypted_fields = ()  # handed as special case by UserSerializer

    resource = AnsibleResourceField(primary_key_field="id")

    def save(self, *args, **kwargs):
        if is_password_usable(self.password) and not password_is_hashed(self.password):
            self.password = make_password(self.password)

        super().save(*args, **kwargs)

    def logout(self):
        logger.debug(f"Logging out user {self.username} from any active backends")
        # cookies = Cookie.objects.filter(user=self)
        # for cookie in cookies:
        #    cookie.logout()

    def summary_fields(self):
        return user_summary_fields(self)
