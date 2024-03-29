import logging
import time
from collections import namedtuple

from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.resource_registry.rest_client import ResourceAPIClient as DABResourceAPIClient
from django.conf import settings
from django.contrib.auth import get_user_model
from requests.models import Response as Response

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster
from aap_gateway_api.utils.jwt_token import create_signed_jwt
from aap_gateway_api.utils.preferences import get_preference_value

ResourceRequestBody = namedtuple("ResourceRequestBody", ["ansible_id", "service_id", "resource_type", "resource_data"], defaults=(None, None, None, None))

logger = logging.getLogger('aap_gateway_api.utils.resource_api_client')


class GWResourceAPIClient(DABResourceAPIClient):
    _jwt_timeout = None
    _jwt = None

    service_paths = {
        ServiceCluster.ServiceType.HUB: "/service-index/",
        ServiceCluster.ServiceType.CONTROLLER: "/v2/service-index/",
        ServiceCluster.ServiceType.EDA: "/v1/service-index/",
    }

    def __init__(self, service: ServiceAPIRoute, user=None, raise_if_bad_request: bool = False):
        http_port = service.http_port
        protocol = "https" if http_port.use_https else "http"
        port = http_port.number
        path = f"/{service.gateway_path.strip('/')}/{self.service_paths[service.service_cluster.service_type].strip('/')}/"

        self.base_url = f"{protocol}://{settings.ENVOY_HOSTNAME}:{port}{path}"

        if user is None:
            user = get_user_model().objects.get(username=settings.SYSTEM_USERNAME)
        self.user = user
        self.header_name = get_preference_value('proxy', 'gateway_token_name')
        self.service = service
        self.raise_if_bad_request = raise_if_bad_request
        self.verify_https = to_python_boolean(settings.VERIFY_ENVOY_HTTPS_CERTIFICATES)

    def refresh_jwt(self):
        # Add a 10 second buffer to the token timeout to account for slower requests.
        self._jwt_timeout = time.time() + get_preference_value("proxy", "gateway_access_token_expiration") - 10
        self._jwt = create_signed_jwt(user=self.user)

    @property
    def jwt(self):
        if self._jwt is None or self._jwt_timeout is None:
            self.refresh_jwt()

        if time.time() >= self._jwt_timeout:
            self.refresh_jwt()

        return self._jwt

    @property
    def requests_auth_kwargs(self):
        return {"headers": {self.header_name: self.jwt}}


class AllServicesClient(GWResourceAPIClient):
    """
    Resources API client that allows the gateway to make requests to all services at once.
    """

    def __init__(self):
        # TODO: Switch to the system user once we can control access to resources api
        user = get_user_model().objects.filter(is_superuser=True).first()

        self.clients = []
        raise_if_bad_request = False

        for service in ServiceAPIRoute.objects.exclude(service_cluster__service_type=ServiceCluster.ServiceType.GATEWAY):
            self.clients.append(GWResourceAPIClient(service, user, raise_if_bad_request))

    # TODO: Make this async
    def _make_request(self, method: str, path: str, data: dict = None, params: dict = None) -> Response:
        responses = {}
        for client in self.clients:
            responses[client.service.api_slug] = client._make_request(method, path, data, params)

        return responses
