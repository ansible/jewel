import logging

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from aap_gateway_api.utils import get_jwt_rsa_key
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.jwt_key')


@extend_schema(
    methods=["GET"],
    request=None,
    responses={"200": OpenApiTypes.STR},
)
class JWTKeyView(AnsibleBaseView):
    permission_classes = []

    def get(self, request):
        try:
            # Return this as text/plain, as it is a PEM file.
            return HttpResponse(get_jwt_rsa_key(public=True), content_type="text/plain")
        except ValueError as e:
            logger.exception(e)
            return HttpResponse(status=500)
