from aap_gateway_api.models import User
from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class UserViewSet(GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer
