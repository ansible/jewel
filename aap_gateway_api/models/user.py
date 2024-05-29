import logging

from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.models import user_summary_fields
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.contrib.auth.hashers import get_hashers_by_algorithm, is_password_usable, make_password
from django.contrib.auth.models import AbstractUser

logger = logging.getLogger('aap.gateway.models.user')


def password_is_hashed(password):
    for algo in get_hashers_by_algorithm().keys():
        if password.startswith(algo):
            return True
    return False


class User(AbstractUser, CommonModel, AuditableModel):
    ignore_relations = [
        'authenticator_users',  # private model
        'groups',  # not using the auth app stuff, see Team model
        'user_permissions',  # not using auth app permissions
        'logentry',  # used for Django admin pages, not the API
        'social_auth',  # Social auth endpoint
        'organizations_administered',  # We are going to merge [teams|orgs] the user is an admin in with [teams|orgs] the user is a member of
        'teams_administered',
        'authenticator_users',  # This is not a model we want on the user endpoint. We actually pull this information up into the user payload
    ]
    activity_stream_excluded_field_names = ['last_login']

    encrypted_fields = ()  # handed as special case by UserSerializer

    resource = AnsibleResourceField(primary_key_field="id")

    def __init__(self, *args, is_system_auditor=False, **kwargs):
        super().__init__(*args, **kwargs)
        if is_system_auditor:
            self._is_system_auditor = True

    def fetch_system_auditor_membership(self):
        "Get from the database True or False, this user is a system auditor"
        from aap_gateway_api.utils.rbac import get_system_auditor_role

        rd = get_system_auditor_role()
        return self.role_assignments.filter(role_definition=rd).exists()

    def apply_system_auditor_membership(self, value):
        from aap_gateway_api.utils.rbac import get_system_auditor_role

        """Change RBAC SystemAuditor role to reflect given value"""
        rd = get_system_auditor_role()
        prior_value = self.fetch_system_auditor_membership()
        if bool(prior_value) != bool(value):
            if prior_value:
                self.role_assignments.filter(role_definition=rd).delete()
            else:
                rd.give_global_permission(self)

        self._is_system_auditor = value

    def save(self, *args, **kwargs):
        is_new_user = bool(not self.pk)

        if is_password_usable(self.password) and not password_is_hashed(self.password):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

        # If the system auditor role was set on unsaved object, apply it now that it is saved
        if is_new_user and hasattr(self, '_is_system_auditor'):
            self.apply_system_auditor_membership(self._is_system_auditor)

    def logout(self):
        logger.debug(f"Logging out user {self.username} from any active backends")
        # cookies = Cookie.objects.filter(user=self)
        # for cookie in cookies:
        #    cookie.logout()

    def summary_fields(self):
        return user_summary_fields(self)

    def get_authenticator_ids(self) -> list[int]:
        return list(self.authenticator_users.values_list('provider__id', flat=True))

    def get_authenticator_uids(self) -> list[str]:
        return list(self.authenticator_users.values_list('uid', flat=True).distinct())

    def get_is_system_auditor(self):
        if not hasattr(self, '_is_system_auditor'):
            # For performance purposes, catch the value from the database
            self._is_system_auditor = self.fetch_system_auditor_membership()
        return self._is_system_auditor

    def set_is_system_auditor(self, value):
        if not self.pk:
            # For unsaved objects, delay application of membership, used in save method
            self._is_system_auditor = value
            return

        if (not hasattr(self, '_is_system_auditor')) or bool(self._is_system_auditor) != bool(value):
            self.apply_system_auditor_membership(value)

    def del_is_system_auditor(self):
        if hasattr(self, '_is_system_auditor'):
            del self._is_system_auditor

    is_system_auditor = property(get_is_system_auditor, set_is_system_auditor, del_is_system_auditor)
