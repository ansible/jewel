from urllib.parse import urljoin

from django.db import models
from rest_framework.reverse import reverse_lazy

from aap_gateway_api.models.common import NamedCommonModel
from aap_gateway_api.models.environment import Environment


class Service(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('environment', 'name', 'service_type')
        models.UniqueConstraint("name", "environment", name="unique_name_environment")

    url_to_proxy_to = models.URLField()
    service_type = models.CharField(
        max_length=1,
        choices=[('g', 'gateway'), ('c', 'controller'), ('h', 'hub'), ('e', 'eda')],
    )
    ignore_ssl = models.BooleanField(
        default=False,
    )
    environment = models.ForeignKey(Environment, on_delete=models.SET_NULL, null=True)

    def get_jwt_login_url(self):
        return urljoin(self.url_to_proxy_to, 'api/gateway/login')

    def get_summary_fields(self):
        res = {}
        if self.environment:
            res['environment'] = self.environment.summary_fields()
        if self.created_by:
            res['created_by'] = self.created_by.summary_fields()
        if self.modified_by:
            res['modified_by'] = self.modified_by.summary_fields()
        return res

    def summary_fields(self):
        res = super.summary_fields()
        res['type'] = self.service_type
        return res

    # What items are related to this object
    def related_fields(self, request):
        res = super().related_fields(request)
        res['environment'] = reverse_lazy('environment-detail', kwargs={'pk': self.environment.pk}, request=request)
        return res
