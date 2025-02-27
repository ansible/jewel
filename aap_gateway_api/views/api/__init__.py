from collections import OrderedDict

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(
    request=None,
    responses={
        "200": inline_serializer(
            "api_gateway_root_view",
            fields={"current_version": serializers.CharField(), "available_versions": serializers.DictField(child=serializers.CharField())},
        )
    },
)
class GatewayRootView(AnsibleBaseView):
    permission_classes = (AllowAny,)
    name = _('gateway')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        v1 = get_relative_url('api_gateway_v1_root_view')
        data = OrderedDict()
        data['current_version'] = v1
        data['available_versions'] = dict(v1=v1)
        return Response(data)
