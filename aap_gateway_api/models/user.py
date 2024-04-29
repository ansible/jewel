import logging

from ansible_base.activitystream.models import AuditableModel
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


class User(AbstractUser, CommonModel, AuditableModel):
    ignore_relations = [
        'authenticator_users',  # private model
        'groups',  # not using the auth app stuff, see Team model
        'user_permissions',  # not using auth app permissions
        'logentry',  # used for Django admin pages, not the API
        'social_auth',  # Social auth endpoint
    ]
    activity_stream_excluded_field_names = ['last_login']

    is_system_auditor = models.BooleanField(default=False, null=False)

    encrypted_fields = ()  # handed as special case by UserSerializer

    resource = AnsibleResourceField(primary_key_field="id")

    def manage_system_auditor_role(self):
        from ansible_base.rbac.models import RoleUserAssignment

        from aap_gateway_api.utils.rbac import get_system_auditor_role

        """Connect User.is_system_auditor with RBAC SystemAuditor role"""
        rd = get_system_auditor_role()
        assignment = RoleUserAssignment.objects.filter(user=self, role_definition=rd).first()
        prior_value = bool(assignment)
        if prior_value != bool(self.is_system_auditor):
            if assignment:
                assignment.delete()
            else:
                rd.give_global_permission(self)

    def save(self, *args, **kwargs):
        if is_password_usable(self.password) and not password_is_hashed(self.password):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)
        self.manage_system_auditor_role()

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
