# Generated with AI assistance: Claude Code (Anthropic)
from importlib import import_module
from unittest import mock

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session

from aap_gateway_api.models.user_session_membership import UserSessionMembership

SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


def _create_session_for_user(user):
    """Create a real session for the given user via the configured session store."""
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store.create()
    return store.session_key


class TestUserSessionMembership:
    def test_membership_created_on_session_save(self, admin_user):
        key = _create_session_for_user(admin_user)
        assert UserSessionMembership.objects.filter(user=admin_user, session_id=key).exists()

    def test_duplicate_membership_not_created(self, admin_user):
        key = _create_session_for_user(admin_user)
        assert UserSessionMembership.objects.filter(user=admin_user, session_id=key).count() == 1

        session = Session.objects.get(session_key=key)
        session.save()
        assert UserSessionMembership.objects.filter(user=admin_user, session_id=key).count() == 1

    def test_no_membership_for_anonymous_session(self):
        store = SessionStore()
        store['some_key'] = 'some_value'
        store.create()
        assert not UserSessionMembership.objects.filter(session_id=store.session_key).exists()

    def test_no_membership_for_corrupted_session(self):
        """get_decoded() raising an exception should not crash the signal handler."""
        store = SessionStore()
        store['some_key'] = 'some_value'
        store.create()
        session = Session.objects.get(session_key=store.session_key)
        with mock.patch.object(session, 'get_decoded', side_effect=ValueError("corrupted")):
            session.save()
        assert not UserSessionMembership.objects.filter(session_id=store.session_key).exists()

    def test_no_membership_for_non_numeric_session_key(self):
        """Non-numeric SESSION_KEY should not crash the signal handler."""
        store = SessionStore()
        store[SESSION_KEY] = 'not-a-number'
        store.create()
        assert not UserSessionMembership.objects.filter(session_id=store.session_key).exists()

    def test_session_update_does_not_trigger_eviction(self, admin_user, preference_manager):
        """Updating an existing session (e.g. extending expiry) must not create a new membership or trigger eviction."""
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            key = _create_session_for_user(admin_user)
            assert UserSessionMembership.objects.filter(user=admin_user).count() == 1

            # Simulate session refresh (Django re-saves the session)
            session = Session.objects.get(session_key=key)
            session.save()

            assert UserSessionMembership.objects.filter(user=admin_user).count() == 1
            assert Session.objects.filter(session_key=key).exists()


class TestSessionEviction:
    def test_no_eviction_when_unlimited(self, admin_user, preference_manager):
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", -1):
            keys = [_create_session_for_user(admin_user) for _ in range(5)]
            assert UserSessionMembership.objects.filter(user=admin_user).count() == 5
            for key in keys:
                assert Session.objects.filter(session_key=key).exists()

    def test_eviction_limit_zero_keeps_only_newest(self, admin_user, preference_manager):
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            key1 = _create_session_for_user(admin_user)
            key2 = _create_session_for_user(admin_user)

            assert not Session.objects.filter(session_key=key1).exists()
            assert Session.objects.filter(session_key=key2).exists()
            assert UserSessionMembership.objects.filter(user=admin_user).count() == 1

    def test_eviction_limit_one_keeps_two(self, admin_user, preference_manager):
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 1):
            key1 = _create_session_for_user(admin_user)
            key2 = _create_session_for_user(admin_user)
            key3 = _create_session_for_user(admin_user)

            assert not Session.objects.filter(session_key=key1).exists()
            assert Session.objects.filter(session_key=key2).exists()
            assert Session.objects.filter(session_key=key3).exists()
            assert UserSessionMembership.objects.filter(user=admin_user).count() == 2

    def test_evicted_session_removed_from_cache(self, admin_user, preference_manager):
        """Verify evicted sessions are cleared from the session cache, not just the DB."""
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            key1 = _create_session_for_user(admin_user)

            store = SessionStore(key1)
            assert store.exists(key1)

            _create_session_for_user(admin_user)

            assert not Session.objects.filter(session_key=key1).exists()

            store = SessionStore(key1)
            assert not store.exists(key1), "Evicted session still found in cache"

    def test_eviction_does_not_affect_other_users(self, admin_user, user_factory, preference_manager):
        other_user = user_factory(username="other_user")
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            other_key = _create_session_for_user(other_user)
            _create_session_for_user(admin_user)
            _create_session_for_user(admin_user)

            assert Session.objects.filter(session_key=other_key).exists()
            assert UserSessionMembership.objects.filter(user=other_user).count() == 1

    @mock.patch("aap_gateway_api.signals.session.log_auth_event")
    def test_eviction_logged(self, mock_log_auth, admin_user, preference_manager):
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            _create_session_for_user(admin_user)
            _create_session_for_user(admin_user)
            assert mock_log_auth.call_count == 1
            assert "evicted 1 session(s)" in mock_log_auth.call_args[0][0]

    def test_expired_sessions_not_counted(self, admin_user, preference_manager):
        """Expired sessions should not count against the limit."""
        from datetime import timedelta

        from django.utils import timezone

        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 1):
            key1 = _create_session_for_user(admin_user)

            session = Session.objects.get(session_key=key1)
            session.expire_date = timezone.now() - timedelta(hours=1)
            session.save()

            key2 = _create_session_for_user(admin_user)
            key3 = _create_session_for_user(admin_user)

            assert Session.objects.filter(session_key=key2).exists()
            assert Session.objects.filter(session_key=key3).exists()


class TestGetActiveMembershipsOverLimit:
    def test_explicit_now_filters_by_provided_time(self, admin_user, preference_manager):
        """Passing now= should use that timestamp instead of the real clock."""
        from datetime import timedelta

        from django.utils import timezone

        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            _create_session_for_user(admin_user)
            _create_session_for_user(admin_user)

            # With now far in the future, all sessions appear expired
            future = timezone.now() + timedelta(days=365)
            over = UserSessionMembership.get_active_memberships_over_limit(admin_user.pk, now=future)
            assert over == []

    def test_explicit_now_in_past_counts_all_as_active(self, admin_user, preference_manager):
        """When now is in the past, all sessions appear active."""
        from datetime import timedelta

        from django.utils import timezone

        # Create 3 sessions with limit disabled so none are evicted
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", -1):
            _create_session_for_user(admin_user)
            _create_session_for_user(admin_user)
            _create_session_for_user(admin_user)

        # Now query with limit=0 and a past timestamp — all 3 are
        # active relative to that time, so 2 should be over the limit
        with preference_manager.set("configuration", "MAX_EXTRA_SESSIONS_PER_USER", 0):
            past = timezone.now() - timedelta(days=365)
            over = UserSessionMembership.get_active_memberships_over_limit(admin_user.pk, now=past)
            assert len(over) == 2

    def test_returns_empty_when_preference_not_set(self, admin_user):
        """SettingNotSetException path: returns [] when MAX_EXTRA_SESSIONS_PER_USER is unregistered."""
        from ansible_base.lib.utils.settings import SettingNotSetException

        _create_session_for_user(admin_user)

        with mock.patch(
            "aap_gateway_api.utils.preferences.get_setting",
            side_effect=SettingNotSetException,
        ):
            over = UserSessionMembership.get_active_memberships_over_limit(admin_user.pk)
            assert over == []
