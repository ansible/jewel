import logging

from aap_gateway_api.serializers.status import PingSerializer
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.api.v1.ping')


class PingView(AnsibleBaseView):
    permission_classes = []
    serializer_class = PingSerializer

    def get(self, request):
        raise RuntimeError("AAP-77439: intentional failure to demo required status check")
