"""Unit tests for audit logging of User, Team, and Organization (AAP-64479).

Ensures that the audit logger receives create, update, delete, and assign/remove
events at INFO level with required content and no secrets.

Uses the project's no_log_messages fixture to suppress other logs and patches
log_auth_event at the signal boundary to capture and assert on audit messages
(same pattern as DAB activitystream tests).
"""

from unittest import mock

import pytest

from aap_gateway_api.models import Organization, Team, User

# Patch where DAB activitystream calls it (signals import log_auth_event at load time)
AUDIT_LOG_PATCH = "ansible_base.activitystream.signals.log_auth_event"


# -----------------------------------------------------------------------------
# Flags: audit_log_enabled on User, Team, Organization (same attribute as DAB AuditableModel)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_class",
    [User, Team, Organization],
    ids=["user", "team", "organization"],
)
def test_model_has_audit_log_enabled(model_class):
    """Models used for audit logging have audit_log_enabled = True (overrides DAB default False)."""
    assert getattr(model_class, "audit_log_enabled", False) is True


# -----------------------------------------------------------------------------
# Audit log records: create, update, delete (and optionally assign/remove)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_user_create(no_log_messages):
    """Creating a User emits an audit log record at INFO with no secrets."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            u = User.objects.create(username="audit-test-user-create", password="NewSecretPassword123!")
    try:
        log_auth_event.assert_called_once()
        msg = log_auth_event.call_args[0][0].lower()
        assert "create" in msg and "user" in msg
        # DAB logs password as '$encrypted$'; no raw password must appear
        assert "newsecretpassword123!" not in msg
        assert "_system" in msg  # Verifies actor is logged, system user in this case
    finally:
        u.delete()


@pytest.mark.django_db
def test_audit_log_user_update(no_log_messages, user):
    """Updating a User emits an audit log record at INFO with no secrets (DAB logs one line per changed field)."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            user.first_name = "Audit"
            user.last_name = "Test"
            user.save()
    assert log_auth_event.call_count == 2
    messages = " ".join(call[0][0].lower() for call in log_auth_event.call_args_list)
    assert "update" in messages and "user" in messages
    assert "password" not in messages or "redact" in messages or "$encrypted$" in messages


@pytest.mark.django_db
def test_audit_log_user_delete(no_log_messages):
    """Deleting a User emits an audit log record at INFO with no secrets."""
    u = User.objects.create(username="audit-test-user-delete")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            u.delete()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "delete" in msg and "user" in msg


@pytest.mark.django_db
def test_audit_log_organization_create(no_log_messages):
    """Creating an Organization emits an audit log record at INFO."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            org = Organization.objects.create(name="Audit Test Org Create")
    try:
        log_auth_event.assert_called_once()
        msg = log_auth_event.call_args[0][0].lower()
        assert "create" in msg and "organization" in msg
    finally:
        org.delete()


@pytest.mark.django_db
def test_audit_log_organization_update(no_log_messages, organization):
    """Updating an Organization emits an audit log record at INFO."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            organization.description = "Updated for audit test"
            organization.save()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "update" in msg and "organization" in msg


@pytest.mark.django_db
def test_audit_log_organization_delete(no_log_messages):
    """Deleting an Organization emits an audit log record at INFO."""
    org = Organization.objects.create(name="Audit Test Org Delete")
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            org.delete()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "delete" in msg and "organization" in msg


@pytest.mark.django_db
def test_audit_log_team_create(no_log_messages, organization):
    """Creating a Team emits an audit log record at INFO."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            team = Team.objects.create(name="Audit Test Team Create", organization=organization)
    try:
        log_auth_event.assert_called_once()
        msg = log_auth_event.call_args[0][0].lower()
        assert "create" in msg and "team" in msg
    finally:
        team.delete()


@pytest.mark.django_db
def test_audit_log_team_update(no_log_messages, team):
    """Updating a Team emits an audit log record at INFO."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            team.description = "Updated for audit test"
            team.save()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "update" in msg and "team" in msg


@pytest.mark.django_db
def test_audit_log_team_delete(no_log_messages, organization):
    """Deleting a Team emits an audit log record at INFO."""
    team = Team.objects.create(name="Audit Test Team Delete", organization=organization)
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            team.delete()
    log_auth_event.assert_called_once()
    msg = log_auth_event.call_args[0][0].lower()
    assert "delete" in msg and "team" in msg


@pytest.mark.django_db
def test_audit_log_user_password_change_redacted(no_log_messages, user):
    """If a password change is audit-logged, raw password must not appear (DAB uses $encrypted$ or excludes it)."""
    with no_log_messages():
        with mock.patch(AUDIT_LOG_PATCH) as log_auth_event:
            user.set_password("NewSecretPassword123!")
            user.save(update_fields=["password"])
    for call in log_auth_event.call_args_list:
        msg = call[0][0]
        assert "NewSecretPassword123!" not in msg, "Raw password must not appear in audit log"
