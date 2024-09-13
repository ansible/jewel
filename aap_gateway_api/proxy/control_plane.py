import json
import logging
import time
import uuid
from io import BytesIO

from ansible_base.authentication.middleware import AuthenticatorBackendMiddleware
from ansible_base.jwt_consumer.common.util import generate_x_trusted_proxy_header
from ansible_base.lib.logging import thread_local as logging_thread_local
from ansible_base.lib.middleware.logging import LogRequestMiddleware
from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError, connections
from django.http import HttpRequest, parse_cookie
from django.views.csrf import csrf_failure
from envoy.config.core.v3.base_pb2 import HeaderValue, HeaderValueOption
from envoy.service.auth.v3 import attribute_context_pb2, external_auth_pb2, external_auth_pb2_grpc
from envoy.type.v3 import http_status_pb2
from google.rpc import status_pb2
from psycopg import OperationalError
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings

from aap_gateway_api.utils import JWTSessionCache, create_signed_jwt, get_jwt_rsa_key, get_preference_value

MIDDLEWARE = [SessionMiddleware, AuthenticatorBackendMiddleware, AuthenticationMiddleware, LogRequestMiddleware]

logger = logging.getLogger('aap.gateway.proxy.control_plane')


def get_drf_request(request: attribute_context_pb2.AttributeContext.HttpRequest) -> DRFRequest:
    d_request = HttpRequest()
    d_request.method = request.method
    d_request.path = request.path

    d_request.COOKIES = parse_cookie(request.headers.get("cookie", ""))

    d_request.META = {**{"HTTP_" + k.upper().replace("-", "_"): v for k, v in request.headers.items()}, "QUERY_STRING": request.query}

    # If we have X-CSRFToken header, we can avoid processing a potentially very large request body for a POST token.
    if d_request.method not in SAFE_METHODS and settings.CSRF_HEADER_NAME not in d_request.META:
        # Set up stream for request body parsing
        d_request._stream = BytesIO(request.raw_body)
        d_request._read_started = False

    d_request.META["SERVER_NAME"] = request.host
    d_request.META.pop("HTTP_ORIGIN", None)  # Force Referer checking for CSRF
    # Needed because body parser will break if called HTTP_CONTENT_LENGTH
    d_request.META["CONTENT_LENGTH"] = d_request.META.pop("HTTP_CONTENT_LENGTH", 0)

    for middleware in MIDDLEWARE:
        middleware(lambda x: x).process_request(d_request)

    # set parsers, in case we are parsing a POST request and need to get csrf tokens from it
    parsers = [parser_class() for parser_class in api_settings.DEFAULT_PARSER_CLASSES]

    req = DRFRequest(d_request, parsers=parsers, authenticators=[x() for x in api_settings.DEFAULT_AUTHENTICATION_CLASSES])

    return req


class ExternalAuth(external_auth_pb2_grpc.AuthorizationServicer):
    def _get_ms_delta(self, start_time):
        delta_ms = (time.time() - start_time) * 1000
        return f'{delta_ms:.0f} (ms)'

    def _log_process_time(self):
        logger.debug(f'GRPC process time for {self.request_id}: {self._get_ms_delta(self.start_time)}')

    def _return_authenticated(self, jwt, username):
        logger.debug(f"User {username} successfully authenticated for {self.request_id}")

        # We are going to send the JWT downstream so we should remove the Authorization header so the service does not see it
        response = external_auth_pb2.OkHttpResponse(
            headers=self.headers
            + [
                HeaderValueOption(header=HeaderValue(key=get_preference_value('proxy', 'gateway_token_name'), value=jwt)),
            ],
            headers_to_remove=['Authorization'],
        )

        self._log_process_time()
        return external_auth_pb2.CheckResponse(ok_response=response)

    def _return_no_authentication_required(self):
        # This endpoint did not require authentication so no logs required
        logger.debug(f"No JWT authentication required for {self.request_id} {self.request_path}")
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse(headers=self.headers))

    def _return_not_authenticated(self):
        logger.info(f"No valid credentials found for user when requesting {self.request_id}.")

        # We're returning an OK response instead of a 403 because the user may have
        # a local credential for the service, or may be requesting an API endpoint
        # that doesn't require authentication. The final decision on whether or
        # not to accept the request is up to the service.
        self._log_process_time()
        return external_auth_pb2.CheckResponse(ok_response=external_auth_pb2.OkHttpResponse(headers=self.headers))

    def _return_bad_csrf(self, request, error: APIException):
        reason = str(error.detail)
        logger.error(f"CSRF verification failure for {self.request_id} - {reason}")

        if "application/json" in request.META.get("HTTP_ACCEPT", ""):
            body = json.dumps(dict(details=reason))
            content_type = "application/json"
        else:
            body = csrf_failure(request, reason).content
            content_type = "text/html"

        # strip trusted proxy header, client makes no use of it.
        self.headers = [HeaderValueOption(header=HeaderValue(key='content-type', value=content_type))]

        response = external_auth_pb2.DeniedHttpResponse(status=http_status_pb2.HttpStatus(code=403), headers=self.headers, body=body)
        status = status_pb2.Status(code=7, message=str(error.detail))

        return external_auth_pb2.CheckResponse(status=status, denied_response=response)

    def _handle_db_error(self, e):
        logger.warning(f"Database error. We think it's a connection error. Resetting the connection so it can be tried again. ({self.request_id})")
        logger.error(e, exc_info=True)
        for conn in connections.all():
            conn.close_if_unusable_or_obsolete()

    def Check(self, request, context):
        self.start_time = time.time()

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
            drf_request = get_drf_request(request.attributes.request.http)
        except (DatabaseError, OperationalError) as e:
            self._handle_db_error(e)
        except Exception as e:
            # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
            logger.exception(e)
            raise

        self.headers = []
        try:
            self.headers.append(
                HeaderValueOption(header=HeaderValue(key='x-trusted-proxy', value=generate_x_trusted_proxy_header(get_jwt_rsa_key()))),
            )
        except Exception:
            logger.exception("Failed to generate x-trusted-proxy")

        self.request_path = request.attributes.request.http.path

        # /static endpoints and any requests to the gateway api do not require any JWT authentication
        if self.request_path.startswith('/api/gateway/') or self.request_path.startswith('/static/'):
            return self._return_no_authentication_required()

        logger.debug(f"Starting authentication for ({self.request_id}) {self.request_path}.")
        try:
            try:
                user = drf_request.user
            except AuthenticationFailed:
                # Rest framework will raise this exception if the user/pass combo is invalid.
                # If this is the case we want to fall though and _return_not_authenticated so that the Authorization header will be sent to the backend.
                user = None

            if not user or not user.pk:
                return self._return_not_authenticated()

            if jwt := JWTSessionCache.get(user.pk):
                logger.debug(f"Loading cached JWT token for {user.username} ({self.request_id})")
            else:
                logger.debug(f"Issuing new JWT token for {user.username} ({self.request_id})")
                jwt_start = time.time()
                jwt = create_signed_jwt(user)
                logger.debug(f"GRPC took {self._get_ms_delta(jwt_start)} to create a signed JWT ({self.request_id})")
                JWTSessionCache.set(user.pk, jwt)

            return self._return_authenticated(jwt, user.username)

        except (DatabaseError, OperationalError) as e:
            self._handle_db_error(e)
        except PermissionDenied as e:
            return self._return_bad_csrf(drf_request, e)
        except Exception as e:
            # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
            logger.exception(e)
            raise


def grpc_hook(server):
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)
