from rest_framework import permissions

from aap_gateway_api.models import AuthenticatorMap
from aap_gateway_api.serializers import AuthenticatorMapSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class AuthenticatorMapViewSet(GatewayModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = AuthenticatorMap.objects.all().order_by("id")
    serializer_class = AuthenticatorMapSerializer
    permission_classes = [permissions.IsAuthenticated]
