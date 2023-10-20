from rest_framework import views, viewsets

from aap_gateway_api.utils import get_api_version
from ansible_base.utils.filtering import CustomFilterBackend


class ViewWithHeaders(views.APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-API-Product-Version'] = get_api_version()
        response['X-API-Product-Name'] = 'Gateway'
        return response


class GatewayModelViewSet(viewsets.ModelViewSet, ViewWithHeaders):
    filter_backends = (CustomFilterBackend,)
