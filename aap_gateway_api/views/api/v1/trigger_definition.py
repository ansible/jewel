from rest_framework.response import Response

from aap_gateway_api.authentication.trigger_definition import TRIGGER_DEFINITION
from aap_gateway_api.views.api.v1.common import ViewWithHeaders


class TriggerDefinitionView(ViewWithHeaders):
    def get(self, request, format=None):
        return Response(TRIGGER_DEFINITION)
