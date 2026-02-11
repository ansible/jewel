import logging
from collections import OrderedDict

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from django.urls.exceptions import NoReverseMatch
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.schemas.generators import EndpointEnumerator

logger = logging.getLogger('aap.gateway.views')


ignore_endpoints = ['docs', 'service-index', 'jwt_key', 'role_metadata', 'feature_flags_state', 'workload_identity_tokens']


GW_V1_ROOT_URL = "/api/gateway/v1"


@extend_schema(request=None, responses={"200": OpenApiTypes.OBJECT})
class V1RootView(AnsibleBaseView):
    permission_classes = (AllowAny,)
    name = _('v1')
    versioning_class = None

    def _find_endpoints_reverse_lookup_names(self, endpoints):
        """
        Attempts to retrieve all possible endpoint names for reverse URL lookup.
        If no matching endpoint name is found, logs an error message.
        Returns:
        - data(dict): A mapping of endpoint names to their corresponding URL paths
        """
        data = OrderedDict()
        endpoints.sort()
        for endpoint in endpoints:
            if endpoint in ignore_endpoints:
                continue

            singular_endpoint = endpoint.rstrip('s')
            if endpoint == 'status':
                singular_endpoint = endpoint

            # Now, we try to form all possible view name patterns
            no_underscore = singular_endpoint.replace('_', '')
            kebab_case = singular_endpoint.replace('_', '-')

            suffixes = ["-list", "-view"]

            # for each base, create a possible view name
            possible_view_name_list = [f"{b}{suffix}" for b in [singular_endpoint, no_underscore, kebab_case] for suffix in suffixes]

            for possible_view_name in possible_view_name_list:
                try:
                    data[endpoint] = get_relative_url(possible_view_name)
                except NoReverseMatch:
                    pass

            if endpoint not in data:
                logger.error(f'{singular_endpoint} had neither a -list nor -view reverse lookup method, ignoring')

        return data

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        """
        This responds to GET requests made to it with a sorted list of available API endpoints
        """
        enumerator = EndpointEnumerator()
        endpoints = []

        # we're using 'junk' because '_' is already used as an alias for gettext_lazy
        for endpoint, junk, junk in enumerator.get_api_endpoints():
            if not endpoint.startswith(GW_V1_ROOT_URL):
                continue

            endpoint = endpoint.replace(GW_V1_ROOT_URL + "/", '').split('/')[0]
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)

        data = self._find_endpoints_reverse_lookup_names(endpoints)

        return Response(data)
