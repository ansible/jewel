from collections import OrderedDict

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from django.core.exceptions import FieldError
from django.db import IntegrityError
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import exception_handler

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.views.api import GatewayRootView  # noqa: F401
from aap_gateway_api.views.api.v1 import V1RootView  # noqa: F401
from aap_gateway_api.views.api.v1.environment import EnvironmentViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.jwt_key import JWTKeyView  # noqa: F401
from aap_gateway_api.views.api.v1.local_login import LoggedLoginView, LoggedLogoutView  # noqa: F401
from aap_gateway_api.views.api.v1.me import MeViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.organization import OrganizationViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.ping import PingView  # noqa: 401
from aap_gateway_api.views.api.v1.preference import PreferenceListViewSet, PreferenceSingletonView  # noqa: F401
from aap_gateway_api.views.api.v1.service import (  # noqa: F401
    AdditionalRouteViewSet,
    HTTPPortViewSet,
    ServiceAPIRouteViewSet,
    ServiceClusterViewSet,
    ServiceNodeViewSet,
)
from aap_gateway_api.views.api.v1.status import StatusView  # noqa: F401
from aap_gateway_api.views.api.v1.team import TeamViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.user import UserViewSet  # noqa: F401


def gateway_exception_handler(exc, context):
    """
    Override default API exception handler to catch IntegrityError exceptions.
    """
    if isinstance(exc, IntegrityError):
        exc = ParseError(exc.args[0])
    if isinstance(exc, FieldError):
        exc = ParseError(exc.args[0])
    return exception_handler(exc, context)


class ApiRootView(AnsibleBaseView):
    permission_classes = (AllowAny,)
    name = _('REST API')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        gateway = reverse('api_gateway_root_view')
        data = OrderedDict()
        data['description'] = _('Gateway REST API')
        data['apis'] = OrderedDict(
            gateway=gateway,
        )
        routes = ServiceAPIRoute.objects.filter(~Q(api_slug='gateway')).order_by('api_slug')
        for route in routes:
            data['apis'][route.api_slug] = route.gateway_path
        return Response(data)
