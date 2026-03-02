"""Unit tests for audit logging of dynamic Preferences (AAP-64919).

Ensures that the audit logger receives create, update, and delete events at
INFO level with required content (actor, target, entity details, action type).

Uses the project's no_log_messages fixture to suppress other logs and patches
log_auth_event at the signal boundary to capture and assert on audit messages
(same pattern as test_audit_log_users_teams_orgs).
"""

from unittest import mock

import pytest
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING

from aap_gateway_api.models import Preference

AUDIT_LOG_PATCH = "ansible_base.activitystream.signals.log_auth_event"


# ---------------------------------------------------------------------------
# Flags: audit_log_enabled
# ---------------------------------------------------------------------------


def test_preference_has_audit_log_enabled():
    """Preference model has audit_log_enabled = True."""
    assert getattr(Preference, "audit_log_enabled", False) is True


# ---------------------------------------------------------------------------
# Audit log records: create, update, delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_preference_create(no_log_messages, register_preference):
    """Creating a Preference emits exactly one audit log record with actor, action, and entity."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            register_preference(
                section="general",
                preference_name="audit_create_test",
                default="initial_value",
                encrypted=False,
                preference_type="string",
            )
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0]
    assert "create" in msg.lower()
    assert "Preference" in msg
    assert "general" in msg
    assert "_system" in msg


@pytest.mark.django_db
def test_audit_log_preference_update(no_log_messages, register_preference):
    """Updating a Preference emits exactly one audit log record with old/new values."""
    register_preference(
        section="general",
        preference_name="audit_update_test",
        default="old_value",
        encrypted=False,
        preference_type="string",
    )
    pref = Preference.objects.get(section="general", name="audit_update_test")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            pref.value = "new_value"
            pref.save()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0]
    assert "update" in msg.lower()
    assert "Preference" in msg
    assert "_system" in msg
    assert "raw_value" in msg
    assert "old_value" in msg
    assert "new_value" in msg


@pytest.mark.django_db
def test_audit_log_preference_delete(no_log_messages, register_preference):
    """Deleting a Preference emits exactly one audit log record."""
    register_preference(
        section="general",
        preference_name="audit_delete_test",
        default="to_be_deleted",
        encrypted=False,
        preference_type="string",
    )
    pref = Preference.objects.get(section="general", name="audit_delete_test")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            pref.delete()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0]
    assert "delete" in msg.lower()
    assert "Preference" in msg
    assert "_system" in msg
    assert "general" in msg


# ---------------------------------------------------------------------------
# Encrypted preference handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_encrypted_preference_create(no_log_messages, register_preference):
    """Creating an encrypted preference masks the value with $encrypted$.

    The dynamic preferences manager triggers a create followed by an update
    (setting the encrypted default), so we expect two audit entries here.
    """
    secret_value = "SuperSecretAPIKey_12345!"
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            register_preference(
                section="general",
                preference_name="audit_enc_create",
                default=secret_value,
                encrypted=True,
                preference_type="string",
            )
    assert log_auth_event.call_count == 2
    for call in log_auth_event.call_args_list:
        msg = call[0][0]
        assert "Preference" in msg
        assert secret_value not in msg, "Plaintext secret must not appear in audit log"
        assert ENCRYPTED_STRING in msg, "Encrypted values should appear as $encrypted$"


@pytest.mark.django_db
def test_audit_log_encrypted_preference_update(no_log_messages, register_preference):
    """Updating an encrypted preference masks both old and new values."""
    old_secret = "old_enc_val"
    new_secret = "new_enc_val"
    register_preference(
        section="general",
        preference_name="audit_enc_update",
        default=old_secret,
        encrypted=True,
        preference_type="string",
    )
    pref = Preference.objects.get(section="general", name="audit_enc_update")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            pref.value = new_secret
            pref.save()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0]
    assert "update" in msg.lower()
    assert "Preference" in msg
    assert old_secret not in msg, "Old plaintext secret must not appear in audit log"
    assert new_secret not in msg, "New plaintext secret must not appear in audit log"
    assert ENCRYPTED_STRING in msg, "Encrypted values should appear as $encrypted$"


@pytest.mark.django_db
def test_audit_log_encrypted_preference_delete(no_log_messages, register_preference):
    """Deleting an encrypted preference masks the value."""
    secret_value = "delete_enc_val"
    register_preference(
        section="general",
        preference_name="audit_enc_delete",
        default=secret_value,
        encrypted=True,
        preference_type="string",
    )
    pref = Preference.objects.get(section="general", name="audit_enc_delete")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            pref.delete()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0]
    assert "delete" in msg.lower()
    assert "Preference" in msg
    assert secret_value not in msg, "Plaintext secret must not appear in audit log on delete"
    assert ENCRYPTED_STRING in msg, "Encrypted values should appear as $encrypted$"
