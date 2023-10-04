from collections import OrderedDict

from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from aap_gateway_api.views.api import GatewayRootView  # noqa: F401
from aap_gateway_api.views.api.v1 import V1RootView  # noqa: F401
from aap_gateway_api.views.api.v1.authenticator import AuthenticatorAuthenticatorMapViewSet, AuthenticatorViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.authenticator_map import AuthenticatorMapViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.environment import EnvironmentOrganizationViewSet, EnvironmentViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.jwt_key import JWTKeyView  # noqa: F401
from aap_gateway_api.views.api.v1.local_login import LoggedLoginView, LoggedLogoutView  # noqa: F401
from aap_gateway_api.views.api.v1.me import MeViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.organization import OrganizationTeamViewSet, OrganizationViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.ping import PingView  # noqa: 401
from aap_gateway_api.views.api.v1.preference import PreferenceListView, PreferenceSingletonView  # noqa: F401
from aap_gateway_api.views.api.v1.service import (  # noqa: F401
    AdditionalRouteViewSet,
    HTTPPortViewSet,
    ServiceAPIRouteViewSet,
    ServiceClusterViewSet,
    ServiceNodeViewSet,
)
from aap_gateway_api.views.api.v1.status import StatusView  # noqa: F401
from aap_gateway_api.views.api.v1.team import TeamViewSet  # noqa: F401
from aap_gateway_api.views.api.v1.trigger_definition import TriggerDefinitionView  # noqa: F401
from aap_gateway_api.views.api.v1.user import UserViewSet  # noqa: F401


class ApiRootView(APIView):
    permission_classes = (AllowAny,)
    name = _('REST API')
    versioning_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, format=None):
        gateway = reverse('api_gateway_root_view')
        data = OrderedDict()
        data['description'] = _('Gateway REST API')
        data['gateway'] = dict(gateway=gateway)
        return Response(data)
