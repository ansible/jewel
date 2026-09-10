from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.serializers import ServiceKeySerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class ServiceKeyViewSet(GatewayModelViewSet):
    """
    API endpoint that allows configuring service authentication keys.
    """

    permission_classes = (
        OAuth2ScopePermission,
        IsSuperuserOrAuditor,
    )
    queryset = ServiceKey.objects.all()
    serializer_class = ServiceKeySerializer
    http_method_names = ['get', 'head', 'options', 'delete', 'patch', 'put']
