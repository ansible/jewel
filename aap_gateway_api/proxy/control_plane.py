import logging

from ansible_base.authentication.middleware import AuthenticatorBackendMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, parse_cookie
from envoy.config.core.v3.base_pb2 import HeaderValue, HeaderValueOption
from envoy.service.auth.v3 import attribute_context_pb2, external_auth_pb2, external_auth_pb2_grpc
from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings

from aap_gateway_api.utils import JWTSessionCache, create_signed_jwt, get_preference_value

MIDDLEWARE = [SessionMiddleware, AuthenticatorBackendMiddleware, AuthenticationMiddleware]

User = get_user_model()
logger = logging.getLogger('aap.gateway.proxy.control_plane')


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
    def _return_authenticated(self, jwt):
        logger.info("User successfully authenticated")

        # TODO: DRF basic auth raises an exception if you pass an invalid username/password
        # regardless of any other auth classes. We need to remove the authentication headers
        # from the proxied request if auth here succeeds. I'm not going to do this now
        # because the gateway isn't configured to use JWT token auth yet.

        return external_auth_pb2.CheckResponse(
            ok_response=external_auth_pb2.OkHttpResponse(
                headers=[HeaderValueOption(header=HeaderValue(key=get_preference_value('proxy', 'gateway_token_name'), value=jwt))]
            )
        )

    def _return_not_authenticated(self):
        logger.info("No authentication")

        # We're returning an OK response instead of a 403 because the user may have
        # a local credential for the service, or may be requesting an API endpoint
        # that doesn't require authentication. The final decision on whether or
        # not to accept the request is up to the service.
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse())

    def Check(self, request, context):
        logger.info("Starting authentication.")
        try:
            drf_request = get_drf_request(request.attributes.request.http)
            user = drf_request.user

            if not user.pk:
                logger.info("No valid credentials found for user.")
                return self._return_not_authenticated()

            if jwt := JWTSessionCache.get(user.pk):
                logger.info("Loading cached JWT token")
                return self._return_authenticated(jwt)
            else:
                logger.info("Issuing new JWT token")
                jwt = create_signed_jwt(user)
                JWTSessionCache.set(user.pk, jwt)
                return self._return_authenticated(jwt)

        # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
        except Exception as e:
            logger.exception(e)
            raise


def grpc_hook(server):
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)
