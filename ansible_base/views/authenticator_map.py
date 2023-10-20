from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from aap_gateway_api.views.api.v1.common import CustomFilterBackend
from ansible_base.models import AuthenticatorMap
from ansible_base.serializers import AuthenticatorMapSerializer


class AuthenticatorMapViewSet(ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = AuthenticatorMap.objects.all().order_by("id")
    serializer_class = AuthenticatorMapSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = (CustomFilterBackend,)
