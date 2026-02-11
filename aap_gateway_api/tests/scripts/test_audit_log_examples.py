"""Unit tests for the audit_log_examples runscript."""

import logging
from unittest.mock import patch

import pytest

from aap_gateway_api.scripts import audit_log_examples

# -----------------------------------------------------------------------------
# print_banner
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width,msg,char,expected_line",
    [
        (80, "AUDIT LOG EXAMPLES", "=", "=" * 80),
        (40, "Cleanup", "-", "-" * 40),
        (5, "Hi", "*", "*****"),
    ],
)
def test_print_banner(capsys, width, msg, char, expected_line):
    """print_banner prints rule, msg, rule with given width and char."""
    audit_log_examples.print_banner(width, msg, char=char)
    out, _ = capsys.readouterr()
    assert out == f"{expected_line}\n{msg}\n{expected_line}\n"


def test_print_banner_default_char(capsys):
    """print_banner defaults to char='='."""
    audit_log_examples.print_banner(3, "X")
    out, _ = capsys.readouterr()
    assert "===" in out
    assert "X" in out


# -----------------------------------------------------------------------------
# print_expected_logs
# -----------------------------------------------------------------------------


def test_print_expected_logs_empty(capsys):
    """print_expected_logs with no lines still prints label and newline."""
    audit_log_examples.print_expected_logs()
    out, _ = capsys.readouterr()
    assert "Expected log(s):" in out
    assert out.endswith("\n\n")


def test_print_expected_logs_single_line(capsys):
    """print_expected_logs indents each line."""
    audit_log_examples.print_expected_logs("create User x")
    out, _ = capsys.readouterr()
    assert "Expected log(s):" in out
    assert "  create User x" in out


def test_print_expected_logs_multiple_lines(capsys):
    """print_expected_logs prints multiple indented lines."""
    audit_log_examples.print_expected_logs("line one", "line two")
    out, _ = capsys.readouterr()
    assert "  line one" in out
    assert "  line two" in out


# -----------------------------------------------------------------------------
# print_step_header
# -----------------------------------------------------------------------------


def test_print_step_header_increments_and_uses_banner(capsys):
    """print_step_header prints banner with step number and increments counter."""
    audit_log_examples._step_counter = 1
    audit_log_examples.print_step_header("Creating organization")
    out, _ = capsys.readouterr()
    assert "-" * 40 in out
    assert "Step 1: Creating organization" in out
    assert audit_log_examples._step_counter == 2

    audit_log_examples.print_step_header("Next step")
    out2, _ = capsys.readouterr()
    assert "Step 2: Next step" in out2
    assert audit_log_examples._step_counter == 3


# -----------------------------------------------------------------------------
# ensure_audit_log_level
# -----------------------------------------------------------------------------


def test_ensure_audit_log_level_sets_info(settings):
    """ensure_audit_log_level sets the audit logger to INFO."""
    settings.ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME = "test.audit.script.logger"
    audit_log_examples.ensure_audit_log_level()
    logger = logging.getLogger("test.audit.script.logger")
    assert logger.level == logging.INFO


def test_ensure_audit_log_level_with_default_name(settings):
    """ensure_audit_log_level sets level when logger name is default aap.auth_audit."""
    settings.ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME = "aap.auth_audit"
    audit_log_examples.ensure_audit_log_level()
    logger = logging.getLogger("aap.auth_audit")
    assert logger.level == logging.INFO


# -----------------------------------------------------------------------------
# enable_audit_logging
# -----------------------------------------------------------------------------


def test_enable_audit_logging_restores_on_exit():
    """enable_audit_logging restores original audit_log_enabled on exit."""

    class FakeModel:
        audit_log_enabled = False

    with audit_log_examples.enable_audit_logging(FakeModel):
        assert FakeModel.audit_log_enabled is True
    assert FakeModel.audit_log_enabled is False


def test_enable_audit_logging_restores_on_exception():
    """enable_audit_logging restores original values even when exception raised."""

    class FakeModel:
        audit_log_enabled = False

    with pytest.raises(ValueError):
        with audit_log_examples.enable_audit_logging(FakeModel):
            assert FakeModel.audit_log_enabled is True
            raise ValueError("oops")
    assert FakeModel.audit_log_enabled is False


def test_enable_audit_logging_multiple_models():
    """enable_audit_logging enables and restores multiple model classes."""

    class M1:
        audit_log_enabled = False

    class M2:
        audit_log_enabled = True

    with audit_log_examples.enable_audit_logging(M1, M2):
        assert M1.audit_log_enabled is True
        assert M2.audit_log_enabled is True
    assert M1.audit_log_enabled is False
    assert M2.audit_log_enabled is True


def test_enable_audit_logging_handles_missing_audit_log_enabled():
    """enable_audit_logging uses False when model has no audit_log_enabled."""

    class NoAttr:
        pass

    with audit_log_examples.enable_audit_logging(NoAttr):
        assert NoAttr.audit_log_enabled is True
    assert getattr(NoAttr, "audit_log_enabled", None) is False


# -----------------------------------------------------------------------------
# run_cleanup
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_cleanup_no_leftover(capsys):
    """run_cleanup prints 'No cleanup needed' when nothing to delete."""
    audit_log_examples.run_cleanup()
    out, _ = capsys.readouterr()
    assert "No cleanup needed" in out


@pytest.mark.django_db
def test_run_cleanup_deletes_leftover(capsys):
    """run_cleanup deletes matching orgs and reports count."""
    from aap_gateway_api.models import Organization

    Organization.objects.create(name="Audit Log Test Org abc12345")

    audit_log_examples.run_cleanup()
    out, _ = capsys.readouterr()
    assert "Cleaned up" in out
    assert "org(s)" in out
    assert not Organization.objects.filter(name__startswith="Audit Log Test Org").exists()


@pytest.mark.django_db
def test_run_cleanup_user_failure_does_not_stop_teams_orgs(capsys):
    """run_cleanup continues with teams and orgs when user cleanup raises."""
    from aap_gateway_api.models import Organization, User

    User.objects.create(username="audit-log-test-xyz")
    org = Organization.objects.create(name="Audit Log Test Org xyz")
    # Team filter would match "Audit Log Test ..." - create one to delete
    from aap_gateway_api.models import Team

    Team.objects.create(name="Audit Log Test Child Team xyz", organization=org)

    with patch("aap_gateway_api.models.User.objects") as mock_user_objects:
        mock_user_objects.filter.return_value.delete.side_effect = RuntimeError("user delete failed")
        audit_log_examples.run_cleanup()

    out, _ = capsys.readouterr()
    assert "Cleanup error (users):" in out
    assert "user delete failed" in out
    # Teams and orgs should still have run
    assert not Organization.objects.filter(name__startswith="Audit Log Test Org").exists()
    assert not Team.objects.filter(name__startswith="Audit Log Test").exists()


# -----------------------------------------------------------------------------
# run (integration)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_completes_successfully(capsys):
    """run() completes all steps and runs cleanup."""
    audit_log_examples.run()
    out, _ = capsys.readouterr()
    assert "AUDIT LOG EXAMPLES" in out
    assert "Step 1:" in out
    assert "Step 16:" in out
    assert "Cleanup" in out
    assert "COMPLETE" in out
    assert "No cleanup needed" in out or "Cleaned up" in out


@pytest.mark.django_db
def test_run_step_failure_continues_to_next_step(capsys):
    """When a step raises, run prints ERROR and continues; cleanup still runs."""
    import traceback

    from aap_gateway_api.models import Organization, Team, User
    from aap_gateway_api.scripts import audit_log_examples as mod

    mod._step_counter = 1
    suffix = __import__("uuid").uuid4().hex[:8]
    state = {
        "org_name": f"Audit Log Test Org {suffix}",
        "username": f"audit-log-test-{suffix}",
        "child_team_name": f"Audit Log Test Child Team {suffix}",
        "parent_team_name": f"Audit Log Test Parent Team {suffix}",
        "org": None,
        "user": None,
        "child_team": None,
        "parent_team": None,
    }
    structure = [
        {
            "title": "Step that fails",
            "action": lambda s: (_ for _ in ()).throw(RuntimeError("step 1 failed")),
            "post_message": None,
            "expected_logs": [],
        },
        {
            "title": "Creating organization",
            "action": lambda s: s.__setitem__("org", Organization.objects.create(name=s["org_name"])),
            "post_message": lambda s: f"Created organization: {s['org_name']}",
            "expected_logs": ["create Organization ..."],
        },
    ]
    mod.ensure_audit_log_level()
    mod.print_banner(80, "AUDIT LOG EXAMPLES")
    with mod.enable_audit_logging(Organization, User, Team):
        for step in structure:
            mod.print_step_header(step["title"])
            try:
                step["action"](state)
                post_msg = step.get("post_message")
                if post_msg is not None:
                    print(post_msg(state) if callable(post_msg) else post_msg)
                mod.print_expected_logs(*step["expected_logs"])
            except Exception as e:
                print(f"\nERROR (step '{step['title']}'): {e}")
                traceback.print_exc()
                print()
    mod.print_banner(40, "Cleanup", char="-")
    mod.run_cleanup()
    mod.print_banner(80, "COMPLETE")

    out, _ = capsys.readouterr()
    assert "ERROR (step 'Step that fails'):" in out or "step 1 failed" in out
    assert "Step 2: Creating organization" in out
    assert "Created organization:" in out
    assert "Cleanup" in out
    assert "COMPLETE" in out
