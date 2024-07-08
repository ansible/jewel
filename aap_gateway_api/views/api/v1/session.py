import logging
from datetime import datetime, timezone

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.contrib.sessions.models import Session
from django.utils.translation import gettext as _
from rest_framework import permissions, status
from rest_framework.response import Response

logger = logging.getLogger('aap.gateway.views.api.v1.session')


class SessionView(AnsibleBaseDjangoAppApiView):
    permission_classes = [OAuth2ScopePermission, permissions.IsAuthenticated]

    def get(self, request, format=None):
        try:
            session = Session.objects.get(session_key=request.session.session_key)
        except Session.DoesNotExist:
            return Response({"detail": _("You do not have an associated session")}, status.HTTP_404_NOT_FOUND)

        expires_date = session.expire_date
        now = datetime.now(timezone.utc)
        delta = expires_date - now
        response = {
            'now': now,
            'expires_on': expires_date,
            'expires_in_seconds': delta.seconds,
        }

        return Response(response)

    def post(self, request, format=None):
        logger.debug(f"Extending session for {request.user} by {request.session.get_expiry_age()}")
        request.session.set_expiry(request.session.get_expiry_age())
        return Response({"message": _("Session extended")})
