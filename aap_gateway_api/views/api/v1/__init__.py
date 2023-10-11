import logging
from collections import OrderedDict

from django.urls.exceptions import NoReverseMatch
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.views import APIView

logger = logging.getLogger('aap.view')


class V1RootView(APIView):
    permission_classes = (AllowAny,)
    name = _('v1')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        data = OrderedDict()
        enumerator = EndpointEnumerator()
        endpoints = []
        for endpoint, junk, junk in enumerator.get_api_endpoints():
            if not endpoint.startswith('/api/gateway/v1'):
                continue

            endpoint = endpoint.replace('/api/gateway/v1/', '').split('/')[0]
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)

        endpoints.sort()
        for endpoint in endpoints:
            singular_endpoint = endpoint.rstrip('s')
            if endpoint == 'status':
                singular_endpoint = endpoint
            try:
                data[endpoint] = reverse(f'{singular_endpoint}-list')
            except NoReverseMatch:
                try:
                    data[endpoint] = reverse(f'{singular_endpoint}-view')
                except NoReverseMatch:
                    logger.error(f'{singular_endpoint} had neither a -list nor -view reverse lookup method, ignoring')

        return Response(data)
