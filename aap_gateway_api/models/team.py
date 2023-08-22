from django.db import models
from rest_framework.reverse import reverse_lazy

from aap_gateway_api.models import User
from aap_gateway_api.models.common import NamedCommonModel
from aap_gateway_api.models.organization import Organization


class Team(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('organization', 'name')
        models.UniqueConstraint("name", "organization", name="unique_name_organization")

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    users = models.ManyToManyField(User, related_name='users', blank=True)

    def get_summary_fields(self):
        res = {}
        if self.organization:
            res['organization'] = self.organization.summary_fields()
        if self.created_by:
            res['created_by'] = self.created_by.summary_fields()
        if self.modified_by:
            res['modified_by'] = self.modified_by.summary_fields()
        return res

    # What items are related to this object
    def related_fields(self, request):
        res = super().related_fields(request)
        res['organization'] = reverse_lazy('organization-detail', kwargs={'pk': self.organization.pk}, request=request)
        return res
