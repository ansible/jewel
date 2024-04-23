from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models import AbstractTeam
from ansible_base.resource_registry.fields import AnsibleResourceField
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models import User


class Team(AbstractTeam, AuditableModel):
    class Meta(AbstractTeam.Meta):
        app_label = 'aap_gateway_api'
        permissions = [('member_team', 'Has all permissions granted to this team')]

    resource = AnsibleResourceField(primary_key_field="id")

    ignore_relations = ['parents', 'teams']

    users = models.ManyToManyField(
        User,
        related_name='teams',
        blank=True,
        help_text=_("The list of users on this team"),
    )

    admins = models.ManyToManyField(
        User,
        related_name='teams_administered',
        blank=True,
        help_text=_("The list of admins for this team"),
    )

    # If we remove this in the future, you can also remove the ignore_relations
    parents = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        help_text=_("The list of teams that are parents of this team"),
    )
