from rest_framework import views, viewsets

from aap_gateway_api.utils import get_api_version


class ViewWithHeaders(views.APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-API-Product-Version'] = get_api_version()
        response['X-API-Product-Name'] = 'AAP Gateway'
        return response


class GatewayModelViewSet(viewsets.ModelViewSet, ViewWithHeaders):
    pass
