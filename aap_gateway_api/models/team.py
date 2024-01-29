from ansible_base.lib.abstract_models import AbstractTeam
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models import User


class Team(AbstractTeam):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('organization', 'name')
        models.UniqueConstraint("name", "organization", name="unique_name_organization")

    users = models.ManyToManyField(
        User,
        related_name='teams',
        blank=True,
        help_text=_("The list of users on this team"),
    )
