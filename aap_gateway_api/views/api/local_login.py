import logging

from django.contrib.auth import views
from rest_framework import status
from rest_framework.exceptions import NotAcceptable
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import StaticHTMLRenderer
from rest_framework.response import Response

logger = logging.getLogger('aap.gateway.local_login')


class LoggedLoginView(views.LoginView):
    def get(self, request, *args, **kwargs):
        # The django.auth.contrib login form doesn't perform the content
        # negotiation we've come to expect from DRF; add in code to catch
        # situations where Accept != text/html (or */*) and reply with
        # an HTTP 406
        try:
            DefaultContentNegotiation().select_renderer(request, [StaticHTMLRenderer], 'html')
        except NotAcceptable:
            resp = Response(status=status.HTTP_406_NOT_ACCEPTABLE)
            resp.accepted_renderer = StaticHTMLRenderer()
            resp.accepted_media_type = 'text/plain'
            resp.renderer_context = {}
            return resp
        return super(LoggedLoginView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        ret = super(LoggedLoginView, self).post(request, *args, **kwargs)
        if request.user.is_authenticated:
            logger.info(f"User {self.request.user.username} logged in from {request.META.get('REMOTE_ADDR', None)}")
            return ret
        else:
            if 'username' in self.request.POST:
                logger.warning(f"Login failed for user {self.request.POST.get('username')} from {request.META.get('REMOTE_ADDR', None)}")
            ret.status_code = 401
            return ret


class LoggedLogoutView(views.LogoutView):
    def dispatch(self, request, *args, **kwargs):
        original_user = getattr(request, 'user', None)
        logger.debug(f"Starting logout of {original_user.username}")
        ret = super(LoggedLogoutView, self).dispatch(request, *args, **kwargs)
        current_user = getattr(request, 'user', None)
        logger.debug(f"After logout of {original_user.username} new user is {current_user.username}")
        if (not current_user or not getattr(current_user, 'pk', True)) and current_user != original_user:
            logger.info(f"User {original_user.username} logged out.")
        else:
            logger.error(f"Logout of {current_user.username} failed!")
        return ret
