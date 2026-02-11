"""
Audit Log Examples Script

Generates example audit log messages for documentation purposes.
This script creates test data, performs various operations that trigger audit logs,
and then cleans up after itself.

Run via django-extensions runscript:
    aap-gateway-manage runscript audit_log_examples

Logging: The script forces the audit logger to INFO level so that audit messages
are emitted regardless of the process's default logging configuration.

The script will:
1. Create an organization (needed for teams)
2. Create a user (with just a username)
3. Update the user's first_name and last_name fields (changed fields - 2 logs)
4. Change the user's first_name and last_name fields again (changed fields - 2 logs)
5. Clear the user's first_name and last_name fields (changed fields - 2 logs)
6. Set password on user (secret change - 1 log, value is hashed in audit)
7. Update password on user (secret change - 1 log, value is hashed in audit)
8. Remove password via set_unusable_password (secret removal - 1 log)
9. Create a child team
10. Create a parent team
11. Associate parent team to child team (M2M association log)
12. Disassociate parent team from child team (M2M disassociation log)
13. Delete the child team
14. Delete the parent team
15. Delete the user
16. Delete the organization
"""

import logging
import traceback
import uuid
from contextlib import contextmanager


def ensure_audit_log_level():
    """
    Force the audit logger to INFO so audit messages are emitted.
    The audit logger name is from ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME.
    """
    from django.conf import settings

    logger_name = getattr(settings, "ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME", "aap.auth_audit")
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)


_step_counter = 1


def print_step_header(title):
    """Print a consistent step header (step number auto-increments)."""
    global _step_counter
    print_banner(40, f"Step {_step_counter}: {title}", char="-")
    _step_counter += 1


def print_banner(width, msg, char="="):
    """Print a horizontal rule, optional message, and same rule (e.g. ===\\nTITLE\\n===)."""
    line = char * width
    print(line)
    print(msg)
    print(line)


def print_expected_logs(*lines):
    """Print the expected logs label followed by indented log lines."""
    print("Expected log(s):")
    for line in lines:
        print(f"  {line}")
    print()


@contextmanager
def enable_audit_logging(*model_classes):
    """
    Context manager to temporarily enable audit logging on the given model classes.
    Enables on enter, restores all original values on exit (even if an exception occurs).
    Use once to cover the whole script so create/update/delete all emit audit logs.
    """
    originals = [(cls, getattr(cls, "audit_log_enabled", False)) for cls in model_classes]
    for cls, _ in originals:
        cls.audit_log_enabled = True
    try:
        yield
    finally:
        for cls, original_value in originals:
            cls.audit_log_enabled = original_value


def run_cleanup():
    """
    Remove any leftover audit-log-example data (users, teams, orgs).
    Each step runs in its own try/except so a failure in one does not stop the rest.
    """
    from aap_gateway_api.models import Organization, Team, User

    deleted_users = deleted_teams = deleted_orgs = None
    try:
        deleted_users = User.objects.filter(username__startswith='audit-log-test-').delete()[0]
    except Exception as e:
        print(f"Cleanup error (users): {e}")
    try:
        deleted_teams = Team.objects.filter(name__startswith='Audit Log Test').delete()[0]
    except Exception as e:
        print(f"Cleanup error (teams): {e}")
    try:
        deleted_orgs = Organization.objects.filter(name__startswith='Audit Log Test Org').delete()[0]
    except Exception as e:
        print(f"Cleanup error (orgs): {e}")

    u = 0 if deleted_users is None else deleted_users
    t = 0 if deleted_teams is None else deleted_teams
    o = 0 if deleted_orgs is None else deleted_orgs
    if u or t or o:
        print(f"Cleaned up {u} user(s), {t} team(s), and {o} org(s)")
    else:
        print("No cleanup needed")


def run(*args):
    """
    Entry point for django-extensions runscript.
    Usage: aap-gateway-manage runscript audit_log_examples
    """
    global _step_counter
    from aap_gateway_api.models import Organization, Team, User

    ensure_audit_log_level()
    _step_counter = 1

    suffix = uuid.uuid4().hex[:8]
    state = {
        "org_name": f'Audit Log Test Org {suffix}',
        "username": f'audit-log-test-{suffix}',
        "child_team_name": f'Audit Log Test Child Team {suffix}',
        "parent_team_name": f'Audit Log Test Parent Team {suffix}',
        "org": None,
        "user": None,
        "child_team": None,
        "parent_team": None,
    }

    # Step actions mutate state; post_message can be str or callable(state) -> str
    structure = [
        {
            "title": "Creating organization",
            "action": lambda s: s.__setitem__("org", Organization.objects.create(name=s["org_name"])),
            "post_message": lambda s: f"Created organization: {s['org_name']}",
            "expected_logs": ["create Organization <org_name> {'name': '<org_name>', ...}"],
        },
        {
            "title": "Creating user (single field)",
            "action": lambda s: s.__setitem__("user", User.objects.create(username=s["username"])),
            "post_message": lambda s: f"Created user: {s['username']}",
            "expected_logs": ["create User <username> {'username': '<username>', ...}"],
        },
        {
            "title": "Setting first_name and last_name",
            "action": lambda s: (setattr(s["user"], "first_name", "John"), setattr(s["user"], "last_name", "Doe"), s["user"].save()),
            "post_message": "Set first_name='John', last_name='Doe'",
            "expected_logs": [
                "update User <username> changed first_name from '' to 'John'",
                "update User <username> changed last_name from '' to 'Doe'",
            ],
        },
        {
            "title": "Changing first_name and last_name",
            "action": lambda s: (setattr(s["user"], "first_name", "Jane"), setattr(s["user"], "last_name", "Smith"), s["user"].save()),
            "post_message": "Changed first_name='Jane', last_name='Smith'",
            "expected_logs": [
                "update User <username> changed first_name from 'John' to 'Jane'",
                "update User <username> changed last_name from 'Doe' to 'Smith'",
            ],
        },
        {
            "title": "Clearing first_name and last_name",
            "action": lambda s: (setattr(s["user"], "first_name", ""), setattr(s["user"], "last_name", ""), s["user"].save()),
            "post_message": "Cleared first_name and last_name",
            "expected_logs": [
                "update User <username> changed first_name from 'Jane' to ''",
                "update User <username> changed last_name from 'Smith' to ''",
            ],
        },
        {
            "title": "Setting password on user",
            "action": lambda s: (s["user"].set_password("InitialPassword1!"), s["user"].save(update_fields=["password"])),
            "post_message": "Set password (initial)",
            "expected_logs": ["update User <username> changed password from '' to '<hash>'"],
        },
        {
            "title": "Updating password on user",
            "action": lambda s: (s["user"].set_password("NewPassword2!"), s["user"].save(update_fields=["password"])),
            "post_message": "Changed password to a new value",
            "expected_logs": ["update User <username> changed password from '<hash>' to '<hash>'"],
        },
        {
            "title": "Removing password (set_unusable_password)",
            "action": lambda s: (s["user"].set_unusable_password(), s["user"].save(update_fields=["password"])),
            "post_message": "Removed password (unusable)",
            "expected_logs": ["update User <username> changed password from '<hash>' to '<unusable>'"],
        },
        {
            "title": "Creating child team",
            "action": lambda s: s.__setitem__(
                "child_team",
                Team.objects.create(name=s["child_team_name"], description="A child team for audit logging", organization=s["org"]),
            ),
            "post_message": lambda s: f"Created child team: {s['child_team_name']}",
            "expected_logs": ["create Team <child_team_name> {'name': '<child_team_name>', 'description': '...', ...}"],
        },
        {
            "title": "Creating parent team",
            "action": lambda s: s.__setitem__(
                "parent_team",
                Team.objects.create(name=s["parent_team_name"], description="A parent team for audit logging", organization=s["org"]),
            ),
            "post_message": lambda s: f"Created parent team: {s['parent_team_name']}",
            "expected_logs": ["create Team <parent_team_name> {'name': '<parent_team_name>', 'description': '...', ...}"],
        },
        {
            "title": "Associating parent team to child team",
            "action": lambda s: s["child_team"].parents.add(s["parent_team"]),
            "post_message": lambda s: f"Added {s['parent_team_name']} as parent of {s['child_team_name']}",
            "expected_logs": ["associate Team <child_team_name> with Team <parent_team_name>"],
        },
        {
            "title": "Disassociating parent team from child team",
            "action": lambda s: s["child_team"].parents.remove(s["parent_team"]),
            "post_message": lambda s: f"Removed {s['parent_team_name']} as parent of {s['child_team_name']}",
            "expected_logs": ["disassociate Team <child_team_name> from Team <parent_team_name>"],
        },
        {
            "title": "Deleting child team",
            "action": lambda s: (s["child_team"].delete(), s.__setitem__("child_team", None)),
            "post_message": lambda s: f"Deleted child team: {s['child_team_name']}",
            "expected_logs": ["delete Team <child_team_name> {'name': '<child_team_name>', ...}"],
        },
        {
            "title": "Deleting parent team",
            "action": lambda s: (s["parent_team"].delete(), s.__setitem__("parent_team", None)),
            "post_message": lambda s: f"Deleted parent team: {s['parent_team_name']}",
            "expected_logs": ["delete Team <parent_team_name> {'name': '<parent_team_name>', ...}"],
        },
        {
            "title": "Deleting user",
            "action": lambda s: (s["user"].delete(), s.__setitem__("user", None)),
            "post_message": lambda s: f"Deleted user: {s['username']}",
            "expected_logs": ["delete User <username> {'username': '<username>', ...}"],
        },
        {
            "title": "Deleting organization",
            "action": lambda s: (s["org"].delete(), s.__setitem__("org", None)),
            "post_message": lambda s: f"Deleted organization: {s['org_name']}",
            "expected_logs": ["delete Organization <org_name> {'name': '<org_name>', ...}"],
        },
    ]

    print_banner(80, "AUDIT LOG EXAMPLES")
    print("\nThis script generates audit log messages for documentation.")
    print("Check your configured audit logger for the output.\n")

    with enable_audit_logging(Organization, User, Team):
        for step in structure:
            print_step_header(step["title"])
            try:
                step["action"](state)
                post_msg = step.get("post_message")
                if post_msg is not None:
                    print(post_msg(state) if callable(post_msg) else post_msg)
                print_expected_logs(*step["expected_logs"])
            except Exception as e:
                print(f"\nERROR (step '{step['title']}'): {e}")
                traceback.print_exc()
                print()

    print_banner(40, "Cleanup", char="-")
    run_cleanup()

    print()
    print_banner(80, "COMPLETE")
    print("\nCheck your audit log output for the actual log messages.")
    print("The logger name is configured via ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME setting.")
