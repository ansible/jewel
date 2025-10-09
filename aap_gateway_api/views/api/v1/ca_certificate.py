from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

from aap_gateway_api.models import CACertificate
from aap_gateway_api.permissions import ServiceTokenAuthOnly
from aap_gateway_api.serializers import CACertificateSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class CACertificateViewSet(GatewayModelViewSet):
    """
    API endpoint that allows to manage a CA Certificate
    """

    queryset = CACertificate.objects.all()
    serializer_class = CACertificateSerializer
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor | ServiceTokenAuthOnly]
