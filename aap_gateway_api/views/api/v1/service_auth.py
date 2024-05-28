from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import ServiceKey
from aap_gateway_api.permissions import IsSystemAdminOrAuditor
from aap_gateway_api.serializers import ServiceKeySerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet


class ServiceKeyViewSet(GatewayModelViewSet):
    """
    API endpoint that allows configuring service authentication keys.
    """

    permission_classes = (IsSystemAdminOrAuditor,)
    queryset = ServiceKey.objects.all()
    serializer_class = ServiceKeySerializer

    def create(self, request, *args, **kwargs):
        # Copied from rest_framework.mixins.CreateModelMixin. This doesn't call super().create
        # because create() returns a response object with the serializer data, whereas we need
        # the original serializer as well as the response data.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        # This returns a one time decrypted version of the token which needs to be configured
        # in the client. By default the serializers return encrypted values as $encrypted$
        resp_data = serializer.data
        resp_data["secret"] = serializer.instance.secret

        return Response(resp_data, status=status.HTTP_201_CREATED, headers=headers)
