# Generated with AI assistance: Claude Code (Anthropic)
import logging

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger('aap.gateway.models.user_session_membership')


class UserSessionMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='session_memberships',
        help_text=_("The user who owns this session."),
    )
    session = models.OneToOneField(
        Session,
        on_delete=models.CASCADE,
        related_name='membership',
        help_text=_("The Django session associated with this membership."),
    )
    created = models.DateTimeField(default=timezone.now, help_text=_("When this session was first tracked."))

    class Meta:
        app_label = 'aap_gateway_api'

    def __str__(self):
        return f'{self.user_id} / {self.session_id}'

    @staticmethod
    def get_active_memberships_over_limit(user_id, now=None):
        from ansible_base.lib.utils.settings import SettingNotSetException

        from aap_gateway_api.utils.preferences import get_setting

        try:
            limit = get_setting('SESSIONS_PER_USER')
        except SettingNotSetException:
            return []

        if limit == -1:
            return []

        if now is None:
            now = timezone.now()

        # Filter expired sessions at the DB level instead of loading
        # all memberships into Python.  select_for_update() prevents
        # two concurrent logins from both reading the same count and
        # each keeping their own session, exceeding the limit.
        active = UserSessionMembership.objects.select_for_update().filter(user_id=user_id, session__expire_date__gt=now).order_by('-created')

        # limit is the number of *additional* sessions beyond the first.
        # So the total allowed is limit + 1.  A limit of 0 means only the
        # single newest session survives.
        allowed = limit + 1
        return list(active[allowed:])
