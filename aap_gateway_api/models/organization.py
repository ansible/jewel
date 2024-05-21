from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.organization import AbstractOrganization
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(AbstractOrganization, AuditableModel):
    class Meta:
        app_label = 'aap_gateway_api'
        permissions = [('member_organization', 'User is a member of this organization')]

    resource = AnsibleResourceField(primary_key_field="id")

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="organizations",
        blank=True,
        help_text=_("The list of users in this organization."),
    )

    admins = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="organizations_administered",
        blank=True,
        help_text=_("The list of admins for this organization."),
    )

    reverse_foreign_key_fields = ['teams']

    managed = models.BooleanField(
        editable=False,
        blank=False,
        default=False,
        help_text=_("Indicates if this organization is managed by the system. It cannot be modified once created."),
    )

    def get_summary_fields(self):
        # TODO: We should probably come up with a more codified and standard
        # way to return this kind of info from models.
        response = super().get_summary_fields()
        response["related_field_counts"] = {}
        response["related_field_counts"]["teams"] = self.teams.count()
        response["related_field_counts"]["users"] = self.users.count()
        return response
