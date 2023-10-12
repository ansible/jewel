import logging
import traceback
from http.cookies import SimpleCookie

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from envoy.config.core.v3.base_pb2 import HeaderValue, HeaderValueOption
from envoy.service.auth.v3 import external_auth_pb2, external_auth_pb2_grpc

from aap_gateway_api.utils import JWTSessionCache, create_signed_jwt, get_preference_value

logger = logging.getLogger('aap.gateway.proxy')


class ExternalAuth(external_auth_pb2_grpc.AuthorizationServicer):
    def _return_authenticated(self, jwt):
        logger.info("User successfully authenticated")
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
            cookie = SimpleCookie()
            session_id = None

            if cookie_header := request.attributes.request.http.headers.get("cookie"):
                cookie.load(cookie_header)

                if session_id := cookie.get(settings.SESSION_COOKIE_NAME):
                    session_id = session_id.value
                else:
                    logger.info(f"'{settings.SESSION_COOKIE_NAME}' cookie does not exist")
                    return self._return_not_authenticated()
            else:
                logger.info("Cookie header not set.")
                return self._return_not_authenticated()

            if jwt := JWTSessionCache.get(session_id):
                logger.info("Loading cached JWT token")
                return self._return_authenticated(jwt)
            try:
                session = Session.objects.get(session_key=session_id)
                user = get_user_model().objects.get(pk=session.get_decoded()["_auth_user_id"])
                logger.info("Creating new JWT token.")
                jwt = create_signed_jwt(user)
                JWTSessionCache.set(session_id, jwt)
                return self._return_authenticated(jwt)

            except Session.DoesNotExist:
                logger.info("Session is invalid.")
                return self._return_not_authenticated()
            except KeyError:
                logger.info("Session is not associated with a user.")
                return self._return_not_authenticated()

        # The GRPC server doesn't seem to be able to catch runtime errors and log a stack trace.
        except Exception as e:
            logger.error(e)
            traceback.print_exc()
            raise


def grpc_hook(server):
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)
