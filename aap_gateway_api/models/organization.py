from django.db import models
from rest_framework.reverse import reverse_lazy

from aap_gateway_api.models.common import NamedCommonModel
from aap_gateway_api.models.environment import Environment


class Organization(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = (
            'environment',
            'name',
        )
        models.UniqueConstraint("name", "environment", name="unique_name_environment")

    environment = models.ForeignKey(Environment, on_delete=models.SET_NULL, null=True)

    def get_summary_fields(self):
        res = {}
        if self.environment:
            res['environment'] = self.environment.summary_fields()
        if self.created_by:
            res['created_by'] = self.created_by.summary_fields()
        if self.modified_by:
            res['modified_by'] = self.modified_by.summary_fields()
        return res

    # What items are related to this object
    def related_fields(self, request):
        res = super().related_fields(request)
        res['environment'] = reverse_lazy('environment-detail', kwargs={'pk': self.environment.pk}, request=request)
        res['teams'] = reverse_lazy('organization-teams', kwargs={'pk': self.pk}, request=request)
        return res
