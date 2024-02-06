import logging

from ansible_base.authentication.middleware import AuthenticatorBackendMiddleware
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, parse_cookie
from envoy.config.core.v3.base_pb2 import HeaderValue, HeaderValueOption
from envoy.service.auth.v3 import attribute_context_pb2, external_auth_pb2, external_auth_pb2_grpc
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings

from aap_gateway_api.utils import JWTSessionCache, create_signed_jwt, get_preference_value

MIDDLEWARE = [SessionMiddleware, AuthenticatorBackendMiddleware, AuthenticationMiddleware]

logger = logging.getLogger('aap.gateway.proxy.control_plane')

# TODO: Someday we should look through the services and find gateway services
#       and get its `/api/gateway` endpoint and stuff it into these instead of hardcoding it.
no_authentication_required = ['/api/gateway/v1/ui_auth/', '/api/gateway/v1/jwt_key/']


def get_drf_request(request: attribute_context_pb2.AttributeContext.HttpRequest) -> DRFRequest:
    d_request = HttpRequest()
    d_request.method = request.method
    d_request.path = request.path
    d_request.COOKIES = parse_cookie(request.headers.get("cookie", ""))

    d_request.META = {**{"HTTP_" + k.upper(): v for k, v in request.headers.items()}, "QUERY_STRING": request.query}

    d_request.META["SERVER_NAME"] = request.host

    for middleware in MIDDLEWARE:
        middleware(lambda x: x).process_request(d_request)

    req = DRFRequest(d_request, authenticators=[x() for x in api_settings.DEFAULT_AUTHENTICATION_CLASSES])

    # Turn off CSRF enforcement
    req._dont_enforce_csrf_checks = True
    return req


class ExternalAuth(external_auth_pb2_grpc.AuthorizationServicer):
    def _return_authenticated(self, jwt, path, username):
        logger.info(f"User {username} successfully authenticated for {path}")

        # Gateway will not accept JWT tokens from itself so we have to allow the auth header to remain if we are going to talk with a gateway endpoint
        # TODO: If we changed gateway to accept its own JWT tokens we could remove this section and just always remove Authorization
        headers_to_remove = []
        if not path.startswith('/api/gateway/'):
            logger.debug(f"Removing authorization header for {path}")
            headers_to_remove.append('Authorization')

        response = external_auth_pb2.OkHttpResponse(
            headers=[
                HeaderValueOption(header=HeaderValue(key=get_preference_value('proxy', 'gateway_token_name'), value=jwt)),
            ],
            headers_to_remove=headers_to_remove,
        )

        return external_auth_pb2.CheckResponse(ok_response=response)

    def _return_no_authentication_required(self, path):
        # This endpoint did not require authentication so no logs required
        logger.debug(f"No authentication required for {path}")
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse())

    def _return_not_authenticated(self, path):
        logger.info(f"No valid credentials found for user when requesting {path}.")

        # We're returning an OK response instead of a 403 because the user may have
        # a local credential for the service, or may be requesting an API endpoint
        # that doesn't require authentication. The final decision on whether or
        # not to accept the request is up to the service.
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse())

    def Check(self, request, context):
        request_path = request.attributes.request.http.path
        if request_path in no_authentication_required or request_path.startswith('/static/'):
            return self._return_no_authentication_required(request_path)

        logger.info(f"Starting authentication for {request_path}.")
        try:
            drf_request = get_drf_request(request.attributes.request.http)
            try:
                user = drf_request.user
            except AuthenticationFailed:
                # Rest framework will raise this exception if the user/pass combo is invalid.
                # If this is the case we want to fall though and _return_not_authenticated so that the Authorization header will be sent to the backend.
                user = None

            if not user or not user.pk:
                return self._return_not_authenticated(request_path)

            if jwt := JWTSessionCache.get(user.pk):
                logger.debug(f"Loading cached JWT token for {user.username}")
            else:
                logger.debug(f"Issuing new JWT token for {user.username}")
                jwt = create_signed_jwt(user)
                JWTSessionCache.set(user.pk, jwt)

            return self._return_authenticated(jwt, request_path, user.username)

        # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
        except Exception as e:
            logger.exception(e)
            raise


def grpc_hook(server):
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)
