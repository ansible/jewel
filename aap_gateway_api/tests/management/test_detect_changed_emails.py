from io import StringIO

import pytest
from ansible_base.activitystream.models import Entry
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

User = get_user_model()

LDAP_TYPE = "ansible_base.authentication.authenticator_plugins.ldap"
LOCAL_TYPE = "ansible_base.authentication.authenticator_plugins.local"


@pytest.fixture
def local_auth(db):
    return Authenticator.objects.get_or_create(
        name="Local Auth",
        defaults={"enabled": True, "type": LOCAL_TYPE, "configuration": {}},
    )[0]


@pytest.fixture
def ldap_auth(db):
    return Authenticator.objects.get_or_create(
        name="Corp LDAP",
        defaults={"enabled": False, "type": LDAP_TYPE, "configuration": {}},
    )[0]


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", email="alice@example.com")


@pytest.fixture
def bob(db):
    return User.objects.create_user(username="bob", email="bob@example.com")


@pytest.fixture
def admin_actor(db):
    return User.objects.create_superuser(username="admin_actor", email="admin@example.com", password="p")


def _create_email_change_entry(target, actor, old_email, new_email):
    user_ct = ContentType.objects.get_for_model(User)
    return Entry.objects.create(
        content_type=user_ct,
        object_id=str(target.pk),
        operation="update",
        changes={"changed_fields": {"email": [old_email, new_email]}},
        created_by=actor,
    )


def _run_command(*args):
    out = StringIO()
    call_command("detect_changed_emails", *args, stdout=out)
    return out.getvalue()


# ---------------------------------------------------------------
# Default mode (no --audit)
# ---------------------------------------------------------------
class TestDefaultMode:
    @pytest.mark.django_db
    def test_no_changes_found(self):
        output = _run_command()
        assert "No email changes found" in output

    @pytest.mark.django_db
    def test_shows_email_changes(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command()
        assert "1 email change(s)" in output
        assert "admin_actor" in output
        assert "alice" in output

    @pytest.mark.django_db
    def test_flags_non_superuser_actor(self, alice, bob):
        _create_email_change_entry(alice, bob, "old@x.com", "new@x.com")
        output = _run_command()
        assert "[NON-SUPERUSER ACTOR]" in output
        assert "--audit" in output

    @pytest.mark.django_db
    def test_flags_self_edit(self, alice):
        _create_email_change_entry(alice, alice, "old@x.com", "new@x.com")
        output = _run_command()
        assert "[SELF-EDIT]" in output

    @pytest.mark.django_db
    def test_does_not_run_audit_sections(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command()
        assert "AUDIT SUMMARY" not in output
        assert "AUTHENTICATOR EMAIL vs USER EMAIL" not in output

    @pytest.mark.django_db
    def test_empty_old_email_shown(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "", "new@x.com")
        output = _run_command()
        assert "(empty)" in output


# ---------------------------------------------------------------
# Audit mode (--audit)
# ---------------------------------------------------------------
class TestAuditMode:
    @pytest.mark.django_db
    def test_runs_all_sections(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "EMAIL CHANGES IN ACTIVITY STREAM" in output
        assert "USERS WITH LOCAL + EXTERNAL AUTHENTICATORS" in output
        assert "AUTHENTICATOR EMAIL vs USER EMAIL MISMATCHES" in output
        assert "DUPLICATE EMAILS ACROSS USERS" in output
        assert "EMAIL CHANGES BY NON-SUPERUSER ACTORS" in output
        assert "EMAIL CHANGES THAT MATCHED ANOTHER EXISTING USER'S EMAIL" in output
        assert "HIGH-RISK" in output
        assert "AUDIT SUMMARY" in output

    @pytest.mark.django_db
    def test_empty_audit(self):
        output = _run_command("--audit")
        assert "No email changes found" in output
        assert "No obvious indicators of email hijacking detected" in output


# ---------------------------------------------------------------
# Dual authenticator detection
# ---------------------------------------------------------------
class TestDualAuthenticators:
    @pytest.mark.django_db
    def test_detects_dual_auth(self, alice, local_auth, ldap_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice")
        AuthenticatorUser.objects.create(user=alice, provider=ldap_auth, uid="alice_ldap")
        output = _run_command("--audit")
        assert "1 user(s) with both local and external authenticators" in output
        assert "alice" in output

    @pytest.mark.django_db
    def test_no_dual_auth(self, alice, local_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice")
        output = _run_command("--audit")
        assert "No users found with both local and external authenticators" in output

    @pytest.mark.django_db
    def test_dual_auth_flags_email_changed(self, alice, admin_actor, local_auth, ldap_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice")
        AuthenticatorUser.objects.create(user=alice, provider=ldap_auth, uid="alice_ldap")
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "EMAIL WAS CHANGED" in output


# ---------------------------------------------------------------
# Email mismatches
# ---------------------------------------------------------------
class TestEmailMismatches:
    @pytest.mark.django_db
    def test_detects_mismatch(self, alice, local_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice", email="different@x.com")
        output = _run_command("--audit")
        assert "1 mismatch(es)" in output

    @pytest.mark.django_db
    def test_no_mismatch_when_same(self, alice, local_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice", email="alice@example.com")
        output = _run_command("--audit")
        assert "No mismatches found" in output


# ---------------------------------------------------------------
# Duplicate emails
# ---------------------------------------------------------------
class TestDuplicateEmails:
    @pytest.mark.django_db
    def test_detects_duplicates(self, db):
        User.objects.create_user(username="dup1", email="same@x.com")
        User.objects.create_user(username="dup2", email="same@x.com")
        output = _run_command("--audit")
        assert "1 email(s) shared by multiple users" in output

    @pytest.mark.django_db
    def test_no_duplicates(self, alice, bob):
        output = _run_command("--audit")
        assert "No duplicate emails found" in output


# ---------------------------------------------------------------
# Non-superuser changes
# ---------------------------------------------------------------
class TestNonSuperuserChanges:
    @pytest.mark.django_db
    def test_detects_non_superuser_change(self, alice, bob):
        _create_email_change_entry(alice, bob, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "1 email change(s) by non-superuser actors" in output

    @pytest.mark.django_db
    def test_no_non_superuser_changes(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "No email changes by non-superuser actors found" in output

    @pytest.mark.django_db
    def test_labels_self_edit_vs_other(self, alice, bob):
        _create_email_change_entry(alice, alice, "old@x.com", "self@x.com")
        _create_email_change_entry(alice, bob, "self@x.com", "other@x.com")
        output = _run_command("--audit")
        assert "SELF-EDIT" in output
        assert "EDITED ANOTHER USER" in output


# ---------------------------------------------------------------
# Suspicious email matches
# ---------------------------------------------------------------
class TestSuspiciousEmailMatches:
    @pytest.mark.django_db
    def test_detects_email_matching_other_user(self, alice, bob, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "bob@example.com")
        output = _run_command("--audit")
        assert "1 suspicious match(es)" in output
        assert "bob" in output

    @pytest.mark.django_db
    def test_no_suspicious_matches(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "unique@x.com")
        output = _run_command("--audit")
        assert "No email changes resulted in a match" in output


# ---------------------------------------------------------------
# High-risk combo
# ---------------------------------------------------------------
class TestHighRiskCombo:
    @pytest.mark.django_db
    def test_detects_high_risk(self, alice, admin_actor, local_auth, ldap_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice")
        AuthenticatorUser.objects.create(user=alice, provider=ldap_auth, uid="alice_ldap")
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "1 high-risk user(s)" in output

    @pytest.mark.django_db
    def test_no_high_risk(self, alice, admin_actor, local_auth):
        AuthenticatorUser.objects.create(user=alice, provider=local_auth, uid="alice")
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "No high-risk combinations found" in output


# ---------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------
class TestSummary:
    @pytest.mark.django_db
    def test_potential_issues_detected(self, alice, bob):
        _create_email_change_entry(alice, bob, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "POTENTIAL ISSUES DETECTED" in output

    @pytest.mark.django_db
    def test_clean_summary(self, alice, admin_actor):
        _create_email_change_entry(alice, admin_actor, "old@x.com", "new@x.com")
        output = _run_command("--audit")
        assert "No obvious indicators of email hijacking detected" in output


# ---------------------------------------------------------------
# Deleted user handling
# ---------------------------------------------------------------
class TestDeletedUser:
    @pytest.mark.django_db
    def test_deleted_target_shown_in_output(self, admin_actor, db):
        temp = User.objects.create_user(username="temp", email="temp@x.com")
        _create_email_change_entry(temp, admin_actor, "old@x.com", "new@x.com")
        temp.delete()
        output = _run_command()
        assert "[DELETED user pk=" in output
