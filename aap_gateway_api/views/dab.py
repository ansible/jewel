from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView

from aap_gateway_api.permissions import IsSystemAdminOrAuditor


class GatewayDABBase(AnsibleBaseView):
    permission_classes = [IsSystemAdminOrAuditor]
