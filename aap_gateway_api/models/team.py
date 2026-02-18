from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models import AbstractTeam
from ansible_base.rbac.managed import TeamAdmin, TeamMember
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models.mixins import UsersMembersMixin


class Team(UsersMembersMixin, AbstractTeam, AuditableModel):
    # Enable audit log for this model
    audit_log_enabled = True

    class Meta(AbstractTeam.Meta):
        app_label = 'aap_gateway_api'
        permissions = [('member_team', 'Has all permissions granted to this team')]

    admin_rd_name = TeamAdmin.name
    member_rd_name = TeamMember.name

    resource = AnsibleResourceField(primary_key_field="id")

    ignore_relations = ['parents', 'teams']

    # If we remove this in the future, you can also remove the ignore_relations
    parents = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        help_text=_("The list of teams that are parents of this team."),
    )
