from ansible_base.activitystream.models import AuditableModel
from django.db import models
from django.utils.translation import gettext_lazy as _

from aap_gateway_api.models.http_port import HTTPPort
from aap_gateway_api.models.route import API_PREFIX, Route


class ServiceAPIRoute(Route, AuditableModel):
    """
    This is a special instance of a route that is intended to be served from /api/ on the
    API port. It has a few requirements that normal Routes don't have.

    - It must be served on the HTTPPort marked as is_api_port=True
    - The gateway_path must be set to /api/{slug}/

    By subclassing the Route model, API routes can be queried along with all of the other
    routes that are configured on Envoy. This makes it much easier to generate the envoy
    xDS configurations.
    """

    router_basename = 'service'

    api_slug = models.SlugField(max_length=20, help_text=_("An internally generated API slug for this Service API Route."))

    class Meta:
        models.UniqueConstraint("service_cluster", name="one_service_api_per_service")

    def save(self, *args, **kwargs):
        self.http_port = HTTPPort.objects.get(is_api_port=True)
        # gateway_path is part of unique key + read only, which means it's repeated in
        # ansible.platform.service collection module
        # Note: when this code is changed, AAPService has to be changed too
        if self.api_slug == 'gateway':
            self.gateway_path = '/'
        else:
            self.gateway_path = API_PREFIX + self.api_slug + "/"

        return super().save(*args, **kwargs)
