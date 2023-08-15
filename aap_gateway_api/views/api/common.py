from rest_framework import views, viewsets


class ViewWithHeaders(views.APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['X-API-Product-Version'] = 'PoC-1'
        response['X-API-Product-Name'] = 'Gateway'
        return response


class GatewayModelViewSet(viewsets.ModelViewSet, ViewWithHeaders):
    pass
