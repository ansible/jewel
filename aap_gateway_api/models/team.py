from ansible_base.lib.abstract_models.common import NamedCommonModel
from django.db import models

from aap_gateway_api.models import User
from aap_gateway_api.models.organization import Organization


class Team(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('organization', 'name')
        models.UniqueConstraint("name", "organization", name="unique_name_organization")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        help_text="The organization the team belongs to",
    )
    users = models.ManyToManyField(
        User,
        related_name='teams',
        blank=True,
        help_text="The list of users on this team",
    )
