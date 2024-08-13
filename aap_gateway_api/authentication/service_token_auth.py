import logging

from ansible_base.lib.utils.response import get_relative_url
from django.core.exceptions import ValidationError
from rest_framework.authentication import BaseAuthentication

from aap_gateway_api.utils.service_token import validate_service_token

logger = logging.getLogger('aap.gateway.authentication.service_token_auth')


class ServiceTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.headers.get("X-ANSIBLE-SERVICE-AUTH", None)

        if token is None:
            return None

        try:
            token_data = validate_service_token(token)

            user = token_data["user"]
            service = token_data["service_cluster"]
            payload = token_data["token_data"]["payload"]

            if self.is_user_authorized(request, user, service, payload):
                return (user, None)
            else:
                logger.info(f"User not authorized to access {request.path}.")
                return None

        except ValidationError:
            logger.info("Invalid token.")
            return None

    def is_user_authorized(self, request, user, service, token_data):
        resources_api = get_relative_url("service-index-root")

        # Allow services to authenticate to the resource registry, regardless of
        # whether or not they are authorized by the user to access the service.
        if request.path.startswith(resources_api):
            allowed_actions = [
                "list",
                "retrieve",
                "service-metadata",
                "manifest",  # resource type manifest like /v1/service-index/resource-types/shared.user/manifest/
                "create",
                "update",
                "delete",
            ]

            setattr(user, "resource_api_actions", allowed_actions)
            return True

        return False
