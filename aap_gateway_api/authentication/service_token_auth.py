import logging
from base64 import b64encode

from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from aap_gateway_api.utils.service_token import validate_service_token

logger = logging.getLogger('aap.gateway.authentication.service_token_auth')


class ServiceTokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword.lower().encode(HTTP_HEADER_ENCODING) or len(auth) != 2:
            logger.info(f"Invalid header, it must be in the form of 'Token <secret>' with no extra spaces: {b64encode(get_authorization_header(request))}")
            return None

        token = auth[1]

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
        resources_api = reverse("service-index-root")

        # Allow services to authenticate to the resource registry, regardless of
        # whether or not they are authorized by the user to access the service.
        if request.path.startswith(resources_api):
            allowed_actions = [
                "list",
                "retrieve",
                "service-metadata",
                "create",
                "update",
                "delete",
            ]

            setattr(user, "resource_api_actions", allowed_actions)
            return True

        return False
