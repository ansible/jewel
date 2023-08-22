from urllib.parse import urljoin

from django.db import models

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

    # Add the service_type to the summary fields
    def summary_fields(self):
        res = super.summary_fields()
        res['service_type'] = self.service_type
        return res
