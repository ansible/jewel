from ansible_base.lib.abstract_models import AbstractDABUser, AbstractOrganization, AbstractTeam, CommonModel
from ansible_base.lib.utils.models import user_summary_fields
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.db import models


class User(AbstractDABUser, CommonModel):
    resource = AnsibleResourceField(primary_key_field="id")

    def summary_fields(self):
        return user_summary_fields(self)


class Organization(AbstractOrganization):
    resource = AnsibleResourceField(primary_key_field="id")

    users = models.ManyToManyField(
        User,
        related_name="organizations",
        blank=True,
        help_text="The list of users in this organization.",
    )

    admins = models.ManyToManyField(
        User,
        related_name="organizations_administered",
        blank=True,
        help_text="The list of admins for this organization.",
    )


class Team(AbstractTeam):
    resource = AnsibleResourceField(primary_key_field="id")

    users = models.ManyToManyField(
        User,
        related_name='teams',
        blank=True,
        help_text="The list of users on this team",
    )

    admins = models.ManyToManyField(
        User,
        related_name='teams_administered',
        blank=True,
        help_text="The list of admins for this team",
    )


class TestPermissionObject(CommonModel):
    class Meta:
        default_permissions = ('view',)

    organization = models.ForeignKey(
        Organization,
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        related_name="testpermissionobjects",
    )
