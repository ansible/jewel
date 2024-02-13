from collections import OrderedDict

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse


class GatewayRootView(AnsibleBaseView):
    permission_classes = (AllowAny,)
    name = _('Gateway')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        v1 = reverse('api_gateway_v1_root_view')
        data = OrderedDict()
        data['current_version'] = v1
        data['available_versions'] = dict(v1=v1)
        return Response(data)
