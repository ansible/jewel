from ansible_base.activitystream.models import AuditableModel
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from aap_gateway_api.models.route import API_PREFIX, Route
from aap_gateway_api.models.ui_plugin_route import PLUGIN_PREFIX


def get_gateway_path_prefix_error_message():
    return _("Custom routes on the API port cannot start with '%(API_PREFIX)s' or '%(PLUGIN_PREFIX)s'") % {
        "API_PREFIX": API_PREFIX,
        "PLUGIN_PREFIX": PLUGIN_PREFIX,
    }


class AdditionalRoute(Route, AuditableModel):
    """
    Use this for configuring additional routes outside of the routes that are served from API_PREFIX.

    This model contains extra validation to ensure that custom routes don't conflict with the services
    that run on the api port.
    """

    router_basename = 'route'

    def clean(self):
        if self.http_port.is_api_port and (self.gateway_path.startswith(API_PREFIX) or self.gateway_path.startswith(PLUGIN_PREFIX)):
            raise ValidationError({"gateway_path": get_gateway_path_prefix_error_message()})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
