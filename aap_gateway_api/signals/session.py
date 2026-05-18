# Generated with AI assistance: Claude Code (Anthropic)
import logging
from importlib import import_module

from ansible_base.lib.logging import log_auth_event
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from aap_gateway_api.models.user_session_membership import UserSessionMembership

logger = logging.getLogger('aap.gateway.signals.session')

User = get_user_model()
SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


@receiver(post_save, sender=Session)
def track_user_session(sender, instance, **kwargs):
    session = instance
    try:
        user_id = session.get_decoded().get(SESSION_KEY)
    except Exception:
        # Corrupted or tampered session data — Django's signing should
        # prevent external tampering, but DB corruption or encoding
        # errors can reach here.  Log so untracked sessions are visible.
        logger.warning("Could not decode session; session is active but untracked by concurrent-session enforcement")
        return

    # Anonymous sessions (CSRF tokens, pre-login browsing) have no
    # user in the session data — nothing to track or enforce.
    if not user_id:
        return

    try:
        user_pk = int(user_id)
    except (ValueError, TypeError):
        logger.warning("Non-numeric SESSION_KEY in session; skipping concurrent-session tracking")
        return

    # User may have been deleted between session creation and this
    # signal (e.g. race with user removal).  No point tracking a
    # session for a user that no longer exists.
    user = User.objects.filter(pk=user_pk).first()
    if not user:
        return

    with transaction.atomic():
        try:
            _, created = UserSessionMembership.objects.get_or_create(
                user_id=user_pk,
                session=session,
                defaults={'created': timezone.now()},
            )
        except IntegrityError:
            return

        if not created:
            return

        expired_memberships = UserSessionMembership.get_active_memberships_over_limit(user_pk)
        if expired_memberships:
            session_keys = [m.session_id for m in expired_memberships]
            for key in session_keys:
                SessionStore(key).delete()
            log_auth_event(
                f"Session limit enforced for user {user.username}: evicted {len(session_keys)} session(s) (MAX_EXTRA_SESSIONS_PER_USER limit exceeded)"
            )
