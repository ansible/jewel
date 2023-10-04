from collections import OrderedDict

from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView


class V1RootView(APIView):
    permission_classes = (AllowAny,)
    name = _('v1')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        data = OrderedDict()
        data['authenticators'] = reverse('authenticator-list', request=request)
        data['authenticator_maps'] = reverse('authenticator-map-list', request=request)
        data['environments'] = reverse('environment-list', request=request)
        data['http-ports'] = reverse('httpport-list', request=request)
        data['me'] = reverse('me-list', request=request)
        data['organization'] = reverse('organization-list', request=request)
        data['ping'] = reverse('ping-view', request=request)
        data['routes'] = reverse('route-list', request=request)
        data['services'] = reverse('service-list', request=request)
        data['service-nodes'] = reverse('servicenode-list', request=request)
        data['service-clusters'] = reverse('servicecluster-list', request=request)
        data['settings'] = reverse('settings-list', request=request)
        data['status'] = reverse('status-view', request=request)
        data['trigger_definition'] = reverse('trigger-definition-view', request=request)
        data['teams'] = reverse('team-list', request=request)
        data['users'] = reverse('user-list', request=request)
        return Response(data)
