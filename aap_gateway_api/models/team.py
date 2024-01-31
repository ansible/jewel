from ansible_base.lib.abstract_models import AbstractTeam
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models import User


class Team(AbstractTeam):
    class Meta(AbstractTeam.Meta):
        app_label = 'aap_gateway_api'

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

    parents = models.ManyToManyField(
        'self',
        blank=True,
        help_text=_("The list of teams that are parents of this team"),
    )
