from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from aap_gateway_api.views.api.v1.common import CustomFilterBackend
from ansible_base.models import Authenticator, AuthenticatorMap
from ansible_base.serializers import AuthenticatorMapSerializer, AuthenticatorSerializer


class AuthenticatorViewSet(ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    filter_backends = (CustomFilterBackend,)
    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer
    permission_classes = [permissions.IsAuthenticated]


class AuthenticatorAuthenticatorMapViewSet(ModelViewSet):
    serializer_class = AuthenticatorMapSerializer

    def get_queryset(self):
        return AuthenticatorMap.objects.filter(authenticator=self.kwargs['pk']).order_by("order")
