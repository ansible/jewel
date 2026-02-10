import json
import logging
import time
import uuid
from io import BytesIO

from ansible_base.authentication.middleware import AuthenticatorBackendMiddleware
from ansible_base.jwt_consumer.common.util import generate_x_trusted_proxy_header
from ansible_base.lib.logging import thread_local as logging_thread_local
from ansible_base.lib.middleware.logging import LogRequestMiddleware
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import close_old_connections
from django.http import HttpRequest, parse_cookie
from django.views.csrf import csrf_failure
from envoy.config.core.v3.base_pb2 import HeaderValue, HeaderValueOption
from envoy.service.auth.v3 import attribute_context_pb2, external_auth_pb2, external_auth_pb2_grpc
from envoy.type.v3 import http_status_pb2
from google.rpc import status_pb2
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings

from aap_gateway_api.common.authentication import SERVICE_TOKEN_AUTH_STRING
from aap_gateway_api.models import ServiceCluster
from aap_gateway_api.utils import JWTSessionCache, create_signed_jwt, get_jwt_rsa_key, get_preference_value

from .service_auth import ServiceAuthHelper

MIDDLEWARE = [SessionMiddleware, AuthenticatorBackendMiddleware, AuthenticationMiddleware, LogRequestMiddleware]

logger = logging.getLogger('aap.gateway.proxy.control_plane')


class EnvoyRequest(HttpRequest):
    """Request class that allows us to override parts of HttpRequest that django expects to be overridden.

    This can be seen as the envoy gRPC alternative to WSGIRequest; it handles overrides needed for request authentication to behave properly.
    """

    def __init__(self, envoy_request: attribute_context_pb2.AttributeContext.HttpRequest):
        self._envoy_request_scheme = envoy_request.scheme
        super().__init__()

    def _get_scheme(self):
        # Overrides the default implementation in Django and returns the scheme
        # from Envoy's request in order to avoid default value that's often incorrect
        return self._envoy_request_scheme


def get_drf_request(request: attribute_context_pb2.AttributeContext.HttpRequest) -> DRFRequest:
    d_request = EnvoyRequest(request)
    d_request.method = request.method
    d_request.path = request.path

    d_request.COOKIES = parse_cookie(request.headers.get("cookie", ""))

    d_request.META = {**{"HTTP_" + k.upper().replace("-", "_"): v for k, v in request.headers.items()}, "QUERY_STRING": request.query}

    # If we have X-CSRFToken header, we can avoid processing a potentially very large request body for a POST token.
    if d_request.method not in SAFE_METHODS and settings.CSRF_HEADER_NAME not in d_request.META:
        # Set up stream for request body parsing
        d_request._stream = BytesIO(request.raw_body)
        d_request._read_started = False

    d_request.META["HTTP_HOST"] = request.host
    # Needed because body parser will break if called HTTP_CONTENT_LENGTH
    d_request.META["CONTENT_LENGTH"] = d_request.META.pop("HTTP_CONTENT_LENGTH", 0)

    for middleware in MIDDLEWARE:
        middleware(lambda x: x).process_request(d_request)

    # set parsers, in case we are parsing a POST request and need to get csrf tokens from it
    parsers = [parser_class() for parser_class in api_settings.DEFAULT_PARSER_CLASSES]

    req = DRFRequest(d_request, parsers=parsers, authenticators=[x() for x in api_settings.DEFAULT_AUTHENTICATION_CLASSES])

    return req


class _ExternalAuth:
    def is_route_internal(self, request) -> bool:
        return request.attributes.context_extensions["is_internal_route"] == "t"

    def _get_ms_delta(self, start_time):
        delta_ms = (time.time() - start_time) * 1000
        return f'{delta_ms:.0f} (ms)'

    def _log_process_time(self):
        logger.debug(f'GRPC process time for {self.request_id}: {self._get_ms_delta(self.start_time)}')

    def _return_authenticated(self, username):
        logger.debug(f"User {username} successfully authenticated for {self.request_id}")

        # Remove original authorization header unless we're overriding it so the service does not see it
        headers_to_remove = [] if any(x for x in self.headers if x.header.key == 'Authorization') else ['Authorization']

        self._add_trusted_proxy_header()
        response = external_auth_pb2.OkHttpResponse(
            headers=self.headers,
            headers_to_remove=headers_to_remove,
        )

        self._log_process_time()
        return external_auth_pb2.CheckResponse(ok_response=response)

    def _return_no_authentication_required(self):
        # This endpoint did not require authentication so no logs required
        logger.debug(f"No JWT authentication required for {self.request_id} {self.request_path}")
        self._add_trusted_proxy_header()
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse(headers=self.headers))

    def _return_not_authenticated(self):
        logger.info(f"No valid credentials found for user when requesting {self.request_id}.")

        # We're returning an OK response instead of a 403 because the user may have
        # a local credential for the service, or may be requesting an API endpoint
        # that doesn't require authentication. The final decision on whether or
        # not to accept the request is up to the service.
        self._log_process_time()
        self._add_trusted_proxy_header()
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse(headers=self.headers))

    def _return_no_auth_with_reason(self, reason, html_body=None, code=7, http_status_code=403):
        if "application/json" in self.drf_request.META.get("HTTP_ACCEPT", ""):
            response_body = json.dumps(dict(details=reason))
            content_type = "application/json"
        else:
            # If we specified an html_body use that, otherwise just return a text body
            if html_body:
                response_body = html_body
                content_type = "text/html"
            else:
                response_body = reason
                content_type = "text/plain"

        # Inject the content-type header for this response
        self.headers = [HeaderValueOption(header=HeaderValue(key='content-type', value=content_type))]

        response = external_auth_pb2.DeniedHttpResponse(status=http_status_pb2.HttpStatus(code=http_status_code), headers=self.headers, body=response_body)
        status = status_pb2.Status(code=code, message=str(reason))

        return external_auth_pb2.CheckResponse(status=status, denied_response=response)

    def _return_bad_csrf(self, error: APIException):
        reason = str(error.detail)
        logger.error(f"CSRF verification failure for {self.request_id} - {reason}")
        return self._return_no_auth_with_reason(reason=reason, html_body=csrf_failure(self.drf_request, reason).content)

    def _ensure_db_availability(self) -> None:
        # Formerly we did a new connection and test read from the DB, but it did not perform
        # well or increase robustness reliably.  Consequently this function is intended to
        # close any stale/broken DB connections on each authentication cycle to avoid issues.
        # We set CONN_HEALTH_CHECKS=True by default, which should also help.
        close_old_connections()

    def _add_trusted_proxy_header(self) -> None:
        try:
            self.headers.append(
                HeaderValueOption(header=HeaderValue(key='x-trusted-proxy', value=generate_x_trusted_proxy_header(get_jwt_rsa_key()))),
            )
        except Exception:
            logger.exception("Failed to generate x-trusted-proxy")

    def get_jwt_for_user(self, user):
        if jwt := JWTSessionCache.get(user.pk):
            logger.debug(f"Loading cached JWT token for {user.username} ({self.request_id})")
        else:
            logger.debug(f"Issuing new JWT token for {user.username} ({self.request_id})")
            jwt_start = time.time()
            jwt = create_signed_jwt(user)
            logger.debug(f"GRPC took {self._get_ms_delta(jwt_start)} to create a signed JWT ({self.request_id})")
            JWTSessionCache.set(user.pk, jwt)

        return jwt

    def _check_oauth2_scope_permission(self, user):
        """
        Check if the OAuth2 token scope permits the requested method.
        Returns a denied response if scope is insufficient, None otherwise.
        """
        if OAuth2ScopePermission().has_permission(self.drf_request, None):
            return None

        # Build detailed log message for auditing
        token = self.drf_request.auth
        if token is None:
            # OAuth2ScopePermission should only return False for OAuth2 tokens,
            # but add defensive check to prevent AttributeError
            return None

        username = user.username if user else '<none>'
        token_scope = getattr(token, 'scope', 'unknown')
        token_pk = getattr(token, 'pk', 'N/A')
        application = getattr(token, 'application', None)
        oauth2_application_pk = application.pk if application else "N/A"
        oauth2_application_name = application.name if application else "Personal Access Token"

        log_message = (
            f"User {username} attempted a {self.drf_request.method} to {self.request_path} through the API "
            f"using OAuth 2 token {token_pk} for OAuth2 application {oauth2_application_pk} ({oauth2_application_name}) "
            f"but token scope '{token_scope}' does not permit this method."
        )
        try:
            from ansible_base.lib.logging import log_auth_warning

            log_auth_warning(log_message)
        except ImportError:
            logger.warning(log_message)

        # Return an error message to the client
        return self._return_no_auth_with_reason("Your token has insufficient scope to perform this action")

    def try_authenticate_request(self):
        try:
            user = self.drf_request.user
        except AuthenticationFailed:
            # Rest framework will raise this exception if the user/pass combo is invalid.
            # If this is the case we want to fall though and _return_not_authenticated so that the Authorization header will be sent to the backend.
            user = None

        if self.is_internal_route:
            if self.drf_request.auth != SERVICE_TOKEN_AUTH_STRING:
                return self._return_no_auth_with_reason("User is not authorized to reach internal route", code=16, http_status_code=401)
            elif self.request_path.startswith('/api/gateway/') or self.request_path.startswith('/static/'):
                return self._return_no_authentication_required()

        if not user or not user.pk:
            return self._return_not_authenticated()

        if scope_denied_response := self._check_oauth2_scope_permission(user):
            return scope_denied_response

        match self.auth_type:
            case ServiceCluster.ServiceAuthType.JWT_AUTH:
                header_name = get_preference_value('proxy', 'gateway_token_name')
                header_val = self.get_jwt_for_user(user)
            case _:
                # Not JWT
                try:
                    (header_name, header_val) = ServiceAuthHelper.get_auth_header(self.service_type, self.auth_type)
                except (NameError, RuntimeError) as e:
                    logger.exception(e)
                    raise

        self.headers.append(HeaderValueOption(header=HeaderValue(key=header_name, value=header_val)))
        return self._return_authenticated(user.username)

    def Check(self, request, context):
        self.start_time = time.time()

        self.headers = []
        self.service_type = request.attributes.context_extensions["service_type"]
        self.auth_type = request.attributes.context_extensions["auth_type"]

        # Clear the thread local request. If we log before we get the new one, we'll log the wrong request.
        logging_thread_local.request = None
        user_request_id = request.attributes.request.http.headers.get('x-request-id')
        sanitized_request_id = 'none'
        if user_request_id:
            try:
                request_id_uuid = uuid.UUID(user_request_id)
                sanitized_request_id = str(request_id_uuid)
            except ValueError:
                logger.exception("Got an invalid request_id")
        self.request_id = sanitized_request_id

        try:
            # Do this ASAP (as soon as we validate the request_id) so that we can log the request_id in the logs.
            self.drf_request = get_drf_request(request.attributes.request.http)
        except Exception as e:
            # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
            logger.exception(e)
            raise

        # Close any old DB connections
        self._ensure_db_availability()

        self.request_path = request.attributes.request.http.path
        self.is_internal_route = self.is_route_internal(request)

        # /static endpoints and any requests to the gateway api do not require any JWT authentication
        # This should never trigger if enable_gateway_auth is set to False on the gateway service.
        if not self.is_internal_route and (self.request_path.startswith('/api/gateway/') or self.request_path.startswith('/static/')):
            return self._return_no_authentication_required()

        # Try to authenticate request: The try block should either return a CheckResponse or raise an error to be handled here.
        logger.debug(f"Starting authentication for ({self.request_id}) {self.request_path}.")
        try:
            return self.try_authenticate_request()
        except PermissionDenied as e:
            return self._return_bad_csrf(e)
        except Exception as e:
            # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
            logger.exception(e)
            raise


class ExternalAuth(external_auth_pb2_grpc.AuthorizationServicer):
    def Check(self, request, context):
        """
        Instantiate a NEW instance to prevent state bleeding across threads.
        """
        return _ExternalAuth().Check(request, context)


def grpc_hook(server):
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)
