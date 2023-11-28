from ansible_base.models.common import NamedCommonModel
from django.db import models

from aap_gateway_api.models.environment import Environment


class Organization(NamedCommonModel):
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
        help_text="The environment this organization belongs to",
        related_name='organizations',
    )

    reverse_foreign_key_fields = ['teams']
