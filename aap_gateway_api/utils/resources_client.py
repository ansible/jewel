import logging
import time
from collections import namedtuple

from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.resource_registry.rest_client import ResourceAPIClient as DABResourceAPIClient
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from requests.models import Response as Response

from aap_gateway_api.utils.jwt_token import create_signed_jwt
from aap_gateway_api.utils.preferences import get_preference_value

ResourceRequestBody = namedtuple("ResourceRequestBody", ["ansible_id", "service_id", "resource_type", "resource_data"], defaults=(None, None, None, None))

logger = logging.getLogger('aap_gateway_api.utils.resource_api_client')


class ServiceTypeChoices(models.TextChoices):
    HUB = "hub", "hub"
    CONTROLLER = "controller", "controller"
    EDA = "eda", "eda"
    GATEWAY = "gateway", "gateway"


class GWResourceAPIClient(DABResourceAPIClient):

    service_paths = {
        ServiceTypeChoices.HUB: "/service-index/",
        ServiceTypeChoices.CONTROLLER: "/v2/service-index/",
        ServiceTypeChoices.EDA: "/v1/service-index/",
    }

    def get_url_for_service(self, service):
        http_port = service.http_port
        protocol = "https" if http_port.use_https else "http"
        port = http_port.number
        path = f"/{service.gateway_path.strip('/')}/{self.service_paths[service.service_cluster.service_type].strip('/')}/"
        return f"{protocol}://{settings.ENVOY_HOSTNAME}:{port}{path}"

    def __init__(self, service: models.Model, user=None, raise_if_bad_request: bool = False):
        self.base_url = self.get_url_for_service(service)

        if user is None:
            user = get_user_model().objects.get(username=settings.SYSTEM_USERNAME)
        self.user = user
        self.header_name = get_preference_value('proxy', 'gateway_token_name')
        self.service = service
        self.raise_if_bad_request = raise_if_bad_request
        self.verify_https = to_python_boolean(settings.ENVOY_VERIFY_HTTPS_CERTIFICATES)

    def refresh_jwt(self):
        # Add a 10 second buffer to the token timeout to account for slower requests.
        self._jwt_timeout = time.time() + get_preference_value("proxy", "gateway_access_token_expiration") - 10
        self._jwt = create_signed_jwt(user=self.user, resource_api_actions="*")


class AllServicesClient(GWResourceAPIClient):
    """
    Resources API client that allows the gateway to make requests to all services at once.
    """

    def __init__(self, user=None, wait_for_response=True):
        self.wait_for_response = wait_for_response

        if user is None:
            user = get_user_model().objects.get(username=settings.SYSTEM_USERNAME)
        self.user = user
        self.header_name = get_preference_value('proxy', 'gateway_token_name')
        self.raise_if_bad_request = False
        self.verify_https = to_python_boolean(settings.ENVOY_VERIFY_HTTPS_CERTIFICATES)

    @property
    def requests_auth_kwargs(self):
        kwargs = {"headers": {self.header_name: self.jwt}}
        if not self.wait_for_response:
            # Requests timeout documentation: https://requests.readthedocs.io/en/latest/user/advanced/#timeouts
            # Allow 4 seconds to make the connection and don't wait for a response.
            kwargs["timeout"] = (4, 0.001)

        return kwargs

    # This function should be async, but that currently isn't possible with the requests library. Some options to
    # consider here for the future are: 1. switch to something like aiohttp, 2. use async.to_thread and run each
    # request in a thread pool, 3. add a tasking system to gateway.
    def _make_request(self, method: str, path: str, data: dict = None, params: dict = None) -> Response:
        from aap_gateway_api.models import ServiceAPIRoute

        responses = {}
        for service in ServiceAPIRoute.objects.exclude(service_cluster__service_type=ServiceTypeChoices.GATEWAY):
            self.base_url = self.get_url_for_service(service)
            responses[service.pk] = super()._make_request(method, path, data, params)

        return responses
