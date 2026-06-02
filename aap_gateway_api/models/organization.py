from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.organization import AbstractOrganization
from ansible_base.rbac.managed import OrganizationAdmin, OrganizationMember
from ansible_base.rbac.models import ObjectRole
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models.mixins import UsersMembersMixin


class Organization(UsersMembersMixin, AbstractOrganization, AuditableModel):
    # Enable audit log for this model
    audit_log_enabled = True

    class Meta:
        app_label = 'aap_gateway_api'
        permissions = [('member_organization', 'User is a member of this organization')]

    admin_rd_name = OrganizationAdmin.name
    member_rd_name = OrganizationMember.name

    resource = AnsibleResourceField(primary_key_field="id")

    managed = models.BooleanField(
        editable=False,
        blank=False,
        default=False,
        help_text=_("Indicates if this organization is managed by the system. It cannot be modified once created."),
    )

    def get_summary_fields(self):
        response = super().get_summary_fields()
        response["related_field_counts"] = {}
        response["related_field_counts"]["teams"] = self.teams.count()

        from aap_gateway_api.models import User

        response["related_field_counts"]["users"] = User.objects.filter(
            has_roles__in=ObjectRole.objects.filter(object_id=self.pk, role_definition__name=self.member_rd_name)
        ).count()

        return response
