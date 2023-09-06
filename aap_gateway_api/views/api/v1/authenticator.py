from rest_framework import permissions

from aap_gateway_api.models import Authenticator
from aap_gateway_api.serializers import AuthenticatorSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class AuthenticatorViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer
    permission_classes = [permissions.IsAuthenticated]
