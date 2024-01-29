from ansible_base.lib.abstract_models.organization import AbstractOrganization
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models.environment import Environment


class Organization(AbstractOrganization):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = (
            'environment',
            'name',
        )
        models.UniqueConstraint("name", "environment", name="unique_name_environment")

    environment = models.ForeignKey(
        Environment,
        on_delete=models.SET_NULL,
        null=True,
        help_text=_("The environment this organization belongs to"),
        related_name='organizations',
    )

    reverse_foreign_key_fields = ['teams']

    def get_summary_fields(self):
        # TODO: We should probably come up with a more codified and standard
        # way to return this kind of info from models.
        response = super().get_summary_fields()
        response["related_field_counts"] = {}
        response["related_field_counts"]["teams"] = self.teams.count()
        response["related_field_counts"]["users"] = self.users.count()
        return response
