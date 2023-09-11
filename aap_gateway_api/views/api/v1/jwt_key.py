import logging

from django.http import HttpResponse
from django.views import View

from aap_gateway_api.utils import get_jwt_rsa_key

logger = logging.getLogger('jwt_key')


class JWTKeyView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse(get_jwt_rsa_key(public=True))
