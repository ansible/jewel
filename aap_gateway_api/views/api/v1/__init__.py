import logging
from collections import OrderedDict

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from django.urls.exceptions import NoReverseMatch
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.schemas.generators import EndpointEnumerator

logger = logging.getLogger('aap.gateway.views')


ignore_endpoints = ['docs']


class V1RootView(AnsibleBaseView):
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
            if endpoint in ignore_endpoints:
                continue

            singular_endpoint = endpoint.rstrip('s')
            if endpoint == 'status':
                singular_endpoint = endpoint

            for possible_view_name in [f'{singular_endpoint}-list', f'{singular_endpoint}-view', f"{singular_endpoint.replace('_', '')}-list"]:
                try:
                    data[endpoint] = reverse(possible_view_name)
                except NoReverseMatch:
                    pass

            if endpoint not in data:
                logger.error(f'{singular_endpoint} had neither a -list nor -view reverse lookup method, ignoring')

        return Response(data)
