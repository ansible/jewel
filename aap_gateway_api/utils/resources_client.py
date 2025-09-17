import copy
import logging
import time
from typing import Callable

from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.resource_registry.rest_client import ResourceAPIClient as DABResourceAPIClient
from ansible_base.resource_registry.rest_client import ResourceRequestBody as DABResourceRequestBody
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from requests.exceptions import Timeout
from requests.models import Response as Response

from aap_gateway_api.models import DefaultServiceType
from aap_gateway_api.utils.jwt_token import create_signed_jwt
from aap_gateway_api.utils.preferences import get_preference_value

ResourceRequestBody = DABResourceRequestBody

logger = logging.getLogger('aap.gateway.utils.resource_api_client')


class GWResourceAPIClient(DABResourceAPIClient):

    def get_default_user(self):
        # This isn't great. Ideally we'd use the _system user, but it's somewhat buggy at the moment.
        # As a stopgap we'll load the first super user. If there aren't any, we'll just use the
        # first user created.
        # The actual user we use here doesn't actually matter from an RBAC perspective. We just need
        # any account to generate an authentication token, since we can't make anonymous requests.
        user = get_user_model().objects.filter(is_superuser=True).first()
        if user is None:
            return get_user_model().objects.first()
        return user

    def get_url_for_service(self, service):
        http_port = service.http_port
        protocol = "https" if http_port.use_https else "http"
        port = http_port.number
        path = f"/{service.gateway_path.strip('/')}/{service.service_cluster.service_type.service_index_path.strip('/')}/"
        return f"{protocol}://{settings.ENVOY_HOSTNAME}:{port}{path}"

    def __init__(self, service: models.Model, user=None, raise_if_bad_request: bool = False):
        self.base_url = self.get_url_for_service(service)

        if user is None:
            user = self.get_default_user()
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
    Resources API client that allows the Gateway to make requests to all services at once.

    args:
        user: user to use for the request.
        wait_for_responses: whether or not to wait for a response from the services
        service_filter: kwargs to be passted to ServiceAPIRoute.objects.filter in case you don't
            want to run the client on all of the services.
    """

    def __init__(self, user=None, wait_for_response=True, service_filter: dict = None):
        self.wait_for_response = wait_for_response
        self.callback = None
        self.service_filter = service_filter

        if user is None:
            user = self.get_default_user()
        self.user = user
        self.header_name = get_preference_value('proxy', 'gateway_token_name')
        self.read_timeout = get_preference_value('proxy', 'resource_client_request_timeout')
        self.raise_if_bad_request = False
        self.verify_https = to_python_boolean(settings.ENVOY_VERIFY_HTTPS_CERTIFICATES)

    @property
    def requests_auth_kwargs(self):
        kwargs = {"headers": {self.header_name: self.jwt}}
        if not self.wait_for_response:
            # Requests timeout documentation: https://requests.readthedocs.io/en/latest/user/advanced/#timeouts
            kwargs["timeout"] = (5, self.read_timeout)

        return kwargs

    def with_callback(self, callback: Callable) -> GWResourceAPIClient:
        cp = copy.deepcopy(self)
        cp.callback = callback
        return cp

    # This function should be async, but that currently isn't possible with the requests library. Some options to
    # consider here for the future are: 1. switch to something like aiohttp, 2. use async.to_thread and run each
    # request in a thread pool, 3. add a tasking system to gateway.
    def _make_request(
        self,
        method: str,
        path: str,
        data: dict = None,
        params: dict = None,
    ) -> Response:
        from aap_gateway_api.models import ServiceAPIRoute

        responses = {}
        svc_qs = ServiceAPIRoute.objects.exclude(service_cluster__service_type__name=DefaultServiceType.GATEWAY.value)
        if self.service_filter:
            svc_qs = svc_qs.filter(**self.service_filter)
        for service in svc_qs:
            self.base_url = self.get_url_for_service(service)
            if self.wait_for_response:
                responses[service.pk] = super()._make_request(method, path, data, params)
            else:
                try:
                    responses[service.pk] = super()._make_request(method, path, data, params)
                except Timeout as e:
                    logger.error(f"Resource client request timeout for {self.base_url} - {type(e).__name__}")
                    responses[service.pk] = None

            if self.callback:
                self.callback(service, responses[service.pk])

        return responses
