"""Tests for role assignment migration in the migrate_service_data command.

The migration uses a PK-based cursor (_CursorStore) to fetch only new
assignments from upstream services.  On each run, it queries with
``id__gt=<snapshot_pk>&order_by=id`` where snapshot_pk is the cursor
value read once at the start of the run and never mutated.

The cursor is advanced in the database after each fully-processed page
for crash safety.  give_permission is idempotent (uses get_or_create
internally), so replaying a partial page after a crash is safe.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.management.commands.migrate_service_data import _CursorStore


def _make_api_response(results, count=None, has_next=False):
    """Build a mock API response with proper status_code and JSON body.

    The PK cursor pagination checks response.status_code before calling
    .json(), so mocks must be explicit Mock objects with status_code=200.
    """
    if count is None:
        count = len(results)
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {
        "count": count,
        "next": "http://fake/next" if has_next else None,
        "results": results,
    }
    return resp


def _make_remote_assignment(
    assignment_type,
    actor_ansible_id,
    role_name,
    pk=None,
    content_type=None,
    object_ansible_id=None,
    object_id=None,
):
    """Build a dict matching the service API assignment response format.

    The ``pk`` (id) field is required for cursor advancement — each assignment
    must have a unique id so the cursor knows where it left off.
    """
    d = {
        f"{assignment_type}_ansible_id": actor_ansible_id,
        "role_definition": role_name,
        "content_type": content_type or "",
        "object_ansible_id": object_ansible_id,
        "object_id": object_id,
    }
    if pk is not None:
        d["id"] = pk
    return d


# =============================================================================
# _CursorStore — raw SQL cursor for PK-based pagination
#
# The cursor's key invariant: self.last_pk is set once in __init__ and
# never mutated.  advance() only persists to the database.  This ensures
# the HTTP id__gt filter stays immutable across all pages of a single run.
# =============================================================================


@pytest.mark.django_db
class TestCursorStore:
    def test_fresh_cursor_has_zero_last_pk(self):
        """A new cursor with no prior data starts at 0."""
        cursor = _CursorStore("controller", "user")
        assert cursor.last_pk == 0

    def test_advance_persists_without_mutating_last_pk(self):
        """advance() writes to DB but does NOT change self.last_pk.

        This is the key invariant that prevents the pagination bug where
        advancing the cursor between pages causes items to be skipped.
        """
        cursor = _CursorStore("controller", "user")
        assert cursor.last_pk == 0

        cursor.advance(42)

        # In-memory value is still 0 — immutable after __init__
        assert cursor.last_pk == 0

        # But a new cursor for the same key reads 42 from DB
        cursor2 = _CursorStore("controller", "user")
        assert cursor2.last_pk == 42

    def test_new_cursor_reads_advanced_value(self):
        """After advance(), a new _CursorStore for the same key reads the persisted value."""
        cursor = _CursorStore("hub", "team")
        cursor.advance(100)

        reloaded = _CursorStore("hub", "team")
        assert reloaded.last_pk == 100

    def test_unique_per_service_and_type(self):
        """Each (service_slug, assignment_type) pair gets its own independent cursor."""
        c1 = _CursorStore("controller", "user")
        c2 = _CursorStore("controller", "team")
        c3 = _CursorStore("hub", "user")

        c1.advance(10)
        c2.advance(20)
        c3.advance(30)

        assert _CursorStore("controller", "user").last_pk == 10
        assert _CursorStore("controller", "team").last_pk == 20
        assert _CursorStore("hub", "user").last_pk == 30

    def test_graceful_degradation_on_load_error(self):
        """If the database is unreachable during load, last_pk defaults to 0.

        This ensures the command can still run (reprocessing all assignments)
        rather than failing outright on a cursor table issue.
        """
        with patch("aap_gateway_api.management.commands.migrate_service_data.connection") as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError("DB unavailable")
            cursor = _CursorStore("controller", "user")

        assert cursor.last_pk == 0

    def test_graceful_degradation_on_advance_error(self):
        """If the database fails during advance(), a warning is logged but
        no exception is raised.

        The next invocation will reprocess from the old cursor position,
        which is safe because give_permission is idempotent.
        """
        cursor = _CursorStore("controller-adv-err", "user")

        with patch("aap_gateway_api.management.commands.migrate_service_data.connection") as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError("DB unavailable")
            # Should not raise — degrades gracefully
            cursor.advance(42)

        # The advance failed, so a new cursor should still read 0
        new_cursor = _CursorStore("controller-adv-err", "user")
        assert new_cursor.last_pk == 0


# =============================================================================
# _paginate_and_create — PK cursor pagination
#
# These tests verify the cursor-based pagination: each page is fetched with
# order_by=id and id__gt=<snapshot_pk>, assignments are created per page,
# and the cursor is advanced in the DB after each fully-processed page.
# The snapshot_pk (cursor.last_pk) stays immutable throughout the run.
# =============================================================================


@pytest.mark.django_db
class TestPaginateAndCreate:
    def _make_cmd(self):
        """Create a minimal Command instance with mocked I/O."""
        cmd = MigrateCommand()
        cmd.client = Mock()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        return cmd

    def test_first_run_creates_all(self):
        """With cursor at 0, all assignments are fetched and created."""
        resp = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Org Admin", pk=1),
                _make_remote_assignment("user", "u2", "Org Admin", pk=2),
            ]
        )

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        # DB cursor advanced, verify by loading a new cursor
        new_cursor = _CursorStore("test-svc", "user")
        assert new_cursor.last_pk == 2

    def test_cursor_applied_to_filters(self):
        """When cursor has a non-zero last_pk, id__gt is added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        # Pre-seed the cursor to 100
        seed = _CursorStore("test-svc-filter", "user")
        seed.advance(100)
        cursor = _CursorStore("test-svc-filter", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert call_filters["id__gt"] == "100"
        assert call_filters["order_by"] == "id"

    def test_cursor_not_in_filters_when_zero(self):
        """When cursor is at 0, id__gt is not added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-zero", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "id__gt" not in call_filters

    def test_cursor_advances_per_page(self):
        """Cursor is advanced in DB after each page, not just at the end.

        This ensures crash safety: if the process is killed between pages,
        at most one page of work is lost.
        """
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", pk=10),
            ],
            has_next=True,
        )
        page2 = _make_api_response(
            [
                _make_remote_assignment("user", "u2", "Role1", pk=20),
            ]
        )

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-pages", "user")
        list_fn = Mock(side_effect=[page1, page2])

        with patch.object(cmd, "_create_assignment", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        # In-memory cursor.last_pk is still 0 (immutable)
        assert cursor.last_pk == 0
        # DB cursor advanced to last page's last PK
        new_cursor = _CursorStore("test-svc-pages", "user")
        assert new_cursor.last_pk == 20

    def test_empty_result_no_cursor_change(self):
        """When API returns 0 results, cursor stays unchanged."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        # Pre-seed cursor
        seed = _CursorStore("test-svc-empty", "user")
        seed.advance(50)
        cursor = _CursorStore("test-svc-empty", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment") as mock_create:
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 0
        mock_create.assert_not_called()
        # DB cursor unchanged
        new_cursor = _CursorStore("test-svc-empty", "user")
        assert new_cursor.last_pk == 50

    def test_http_error_raises_immediately_with_body_preview(self):
        """HTTP error raises RuntimeError immediately with response body preview.

        The PK cursor provides crash recovery: the installer re-runs the
        command and the cursor resumes from the last completed page,
        making per-page retry redundant.  The response body is included
        so operators can diagnose upstream errors.
        """
        error_resp = Mock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error: database connection lost"

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-err", "user")
        list_fn = Mock(return_value=error_resp)

        with pytest.raises(RuntimeError, match="Failed to fetch user assignments page 1: HTTP 500"):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        # Called exactly once — no retry
        assert list_fn.call_count == 1

    def test_http_error_mid_pagination_saves_cursor(self):
        """HTTP error on page 2: page 1 assignments created, cursor saved at
        page 1's last PK so the next run resumes from there."""
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", pk=10),
            ],
            has_next=True,
        )
        error_resp = Mock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-mid", "user")
        # page1 succeeds, page2 fails immediately
        list_fn = Mock(side_effect=[page1, error_resp])

        with patch.object(cmd, "_create_assignment", return_value=True):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

        # DB cursor saved at page 1's last PK — next run resumes from here
        new_cursor = _CursorStore("test-svc-mid", "user")
        assert new_cursor.last_pk == 10

    def test_missing_pk_raises_runtime_error(self):
        """If the API returns an assignment without an 'id' field, raise
        RuntimeError immediately rather than silently leaving the cursor
        unchanged.

        Without 'id', the cursor cannot advance and every subsequent run
        would reprocess all assignments. This indicates an incompatible
        DAB version (requires PR 1032+).
        """
        resp = _make_api_response(
            [
                {"user_ansible_id": "u1", "role_definition": "Role1"},
            ]
        )

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-nopk", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment", return_value=True):
            with pytest.raises(RuntimeError, match="without 'id' field"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

    def test_role_exclusion_filter_applied(self):
        """Role exclusion filter is passed to the API when non-empty."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-excl", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", ["Platform Auditor", "Organization Admin"], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "not__role_definition__name__in" in call_filters

    def test_multi_page_snapshot_prevents_skipping(self):
        """Verify that id__gt filter uses the snapshot value, not the
        advancing DB cursor value.

        This is a regression test for the bug where advancing the cursor
        in the database after each page caused the HTTP filter to drift,
        making page N+1 skip items whose PKs fell between the old and
        new cursor values.

        With the fix, cursor.last_pk is set once in __init__ and never
        mutated, so the id__gt filter stays constant across all pages.
        """
        page1 = _make_api_response(
            [_make_remote_assignment("user", "u1", "Role1", pk=10)],
            has_next=True,
        )
        page2 = _make_api_response(
            [_make_remote_assignment("user", "u2", "Role1", pk=20)],
        )

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-snapshot", "user")
        list_fn = Mock(side_effect=[page1, page2])

        with patch.object(cmd, "_create_assignment", return_value=True):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        # Both pages used the initial snapshot (0), so no id__gt on either
        page1_filters = list_fn.call_args_list[0][1]["filters"]
        page2_filters = list_fn.call_args_list[1][1]["filters"]
        assert "id__gt" not in page1_filters
        assert "id__gt" not in page2_filters

        # But cursor was advanced in DB for crash recovery
        new_cursor = _CursorStore("test-svc-snapshot", "user")
        assert new_cursor.last_pk == 20


# =============================================================================
# migrate_role_assignments — orchestration
# =============================================================================


@pytest.mark.django_db
class TestMigrateRoleAssignments:
    """Tests for the orchestration layer that loops over assignment types
    (user, team) and delegates to _paginate_and_create."""

    def _make_cmd(self):
        """Create a minimal Command instance with mocked I/O."""
        cmd = MigrateCommand()
        cmd.client = Mock()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        return cmd

    def test_processes_user_and_team(self):
        """Both user and team assignment types are processed with separate cursors."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=3) as mock_paginate,
            patch.object(cmd, "_check_for_drift", return_value=False),
        ):
            cmd.migrate_role_assignments("controller", "controller")

        # Called twice: once for user, once for team
        assert mock_paginate.call_count == 2
        call_types = [call[0][1] for call in mock_paginate.call_args_list]
        assert call_types == ["user", "team"]

    def test_creates_cursors_per_service(self):
        """Each service gets its own cursor records in the DB."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=0),
            patch.object(cmd, "_check_for_drift", return_value=False),
        ):
            cmd.migrate_role_assignments("controller", "controller")

        # Verify cursors were created by loading them
        user_cursor = _CursorStore("controller", "user")
        team_cursor = _CursorStore("controller", "team")
        # They should exist (loaded from DB, defaulting to 0)
        assert user_cursor.last_pk == 0
        assert team_cursor.last_pk == 0

    def test_http_failure_propagates(self):
        """RuntimeError from _paginate_and_create propagates to fail the service."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", side_effect=RuntimeError("HTTP 500")):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                cmd.migrate_role_assignments("controller", "controller")

    def test_drift_detected_raises_runtime_error(self):
        """When the post-run drift check detects new assignments, RuntimeError
        is raised so the installer retries and the cursor picks up the new items."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=5),
            patch.object(cmd, "_check_for_drift", return_value=True),
        ):
            with pytest.raises(RuntimeError, match="concurrent modifications were detected"):
                cmd.migrate_role_assignments("controller", "controller")

    def test_no_drift_completes_normally(self):
        """When the post-run drift check finds no new items, the method
        completes without raising."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=5),
            patch.object(cmd, "_check_for_drift", return_value=False),
        ):
            cmd.migrate_role_assignments("controller", "controller")

        # Should not raise — verify output was written
        cmd.stdout.write.assert_any_call("Role assignment migration for controller completed (10 total created)")

    def test_check_for_drift_queries_beyond_cursor(self):
        """_check_for_drift loads a fresh cursor from DB and asks the API
        if any items exist beyond it."""
        cmd = self._make_cmd()

        # Pre-seed cursor to PK=100
        seed = _CursorStore("drift-check-svc", "user")
        seed.advance(100)

        # API returns count > 0 — drift detected
        drift_resp = Mock()
        drift_resp.status_code = 200
        drift_resp.json.return_value = {"count": 3}
        list_fn = Mock(return_value=drift_resp)

        assert cmd._check_for_drift(list_fn, "user", "drift-check-svc") is True
        call_filters = list_fn.call_args[1]["filters"]
        assert call_filters["id__gt"] == "100"
        assert call_filters["page_size"] == "1"

    def test_check_for_drift_returns_false_when_no_new_items(self):
        """_check_for_drift returns False when the API returns count=0."""
        cmd = self._make_cmd()

        seed = _CursorStore("drift-empty-svc", "user")
        seed.advance(50)

        no_drift_resp = Mock()
        no_drift_resp.status_code = 200
        no_drift_resp.json.return_value = {"count": 0}
        list_fn = Mock(return_value=no_drift_resp)

        assert cmd._check_for_drift(list_fn, "user", "drift-empty-svc") is False

    def test_check_for_drift_skips_when_cursor_is_zero(self):
        """_check_for_drift skips the API call when cursor is at 0
        (fresh install with no prior progress to check against)."""
        cmd = self._make_cmd()
        list_fn = Mock()

        assert cmd._check_for_drift(list_fn, "user", "drift-zero-svc") is False
        list_fn.assert_not_called()

    def test_check_for_drift_returns_false_on_api_error(self):
        """If the drift check API call fails, assume no drift and continue.

        The drift check is best-effort — a transient network error should
        not block the migration from completing.
        """
        cmd = self._make_cmd()

        seed = _CursorStore("drift-err-svc", "user")
        seed.advance(50)

        list_fn = Mock(side_effect=RuntimeError("connection refused"))

        assert cmd._check_for_drift(list_fn, "user", "drift-err-svc") is False


# =============================================================================
# _create_assignment
# =============================================================================


@pytest.mark.django_db
class TestCreateAssignment:
    """Tests for _create_assignment: resolving and creating role assignments
    from raw API response dicts.

    Each resolution step (role definition, actor, content object) has its
    own error handling so operators get specific messages identifying what
    failed and why — including actor, role, and object identifiers.
    """

    def test_missing_actor_returns_false_silently(self):
        """Missing actor ansible_id returns False without logging — the API
        response is malformed and there's nothing actionable to report."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = {"role_definition": "Some Role", "user_ansible_id": None}
        assert cmd._create_assignment(assignment, "user") is False
        cmd.stderr.write.assert_not_called()

    def test_missing_role_returns_false_silently(self):
        """Missing role_definition returns False without logging."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = {"user_ansible_id": "user-uuid-1", "role_definition": None}
        assert cmd._create_assignment(assignment, "user") is False
        cmd.stderr.write.assert_not_called()

    def test_missing_role_definition_returns_false(self):
        """Non-existent role definition returns False with error message
        that includes both the role name and the actor identifier."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("user", "user-uuid", "NonexistentRole")
        assert cmd._create_assignment(assignment, "user") is False
        msg = cmd.stderr.write.call_args[0][0]
        assert "Unable to find role definition 'NonexistentRole'" in msg
        assert "actor user-uuid" in msg

    def test_missing_actor_resource_returns_false(self):
        """Non-existent actor resource returns False with error message
        that includes both the actor identifier and the role name."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        RoleDefinition.objects.get_or_create(
            name="Test Role Create",
            defaults={"managed": False},
        )
        fake_id = str(uuid.uuid4())
        assignment = _make_remote_assignment("user", fake_id, "Test Role Create")
        assert cmd._create_assignment(assignment, "user") is False
        msg = cmd.stderr.write.call_args[0][0]
        assert f"Unable to find user with ansible_id {fake_id}" in msg
        assert "role 'Test Role Create'" in msg

    def test_global_assignment_created(self):
        """Global assignment (no content object) is created via give_global_permission."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="global-perm-user")
        RoleDefinition.objects.get_or_create(name="Test Global Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("user", str(user.resource.ansible_id), "Test Global Role")
        assert cmd._create_assignment(assignment, "user") is True

    def test_org_assignment_created(self):
        """Organization assignment is created by resolving the object via Resource ansible_id."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="org-perm-user")
        org = Organization.objects.create(name="test-perm-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(
            name="Test Org Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment(
            "user",
            str(user.resource.ansible_id),
            "Test Org Role",
            content_type="shared.organization",
            object_ansible_id=str(org.resource.ansible_id),
        )
        assert cmd._create_assignment(assignment, "user") is True

    def test_team_assignment_created(self):
        """Team content type assignment is created by resolving via Resource ansible_id."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, Team, User

        user = User.objects.create(username="team-perm-user")
        org = Organization.objects.create(name="test-team-perm-org")
        team = Team.objects.create(name="test-perm-team", organization=org)
        ct = DABContentType.objects.get_for_model(team)
        RoleDefinition.objects.get_or_create(
            name="Test Team Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment(
            "user",
            str(user.resource.ansible_id),
            "Test Team Role",
            content_type="shared.team",
            object_ansible_id=str(team.resource.ansible_id),
        )
        assert cmd._create_assignment(assignment, "user") is True

    def test_team_actor_global_assignment_created(self):
        """Team actor assignment uses team_ansible_id (not user_ansible_id).

        The assignment_type controls which key is used to extract the
        actor identifier from the API response dict. This test verifies
        that the 'team' path works end-to-end with a Team as the actor.
        """
        from aap_gateway_api.models import Organization, Team

        org = Organization.objects.create(name="team-actor-org")
        team = Team.objects.create(name="team-actor-team", organization=org)
        RoleDefinition.objects.get_or_create(name="Test Team Actor Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("team", str(team.resource.ansible_id), "Test Team Actor Role")
        assert cmd._create_assignment(assignment, "team") is True

    def test_remote_object_assignment_created(self):
        """Service-specific assignment is created by wrapping the PK in a RemoteObject."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import User

        user = User.objects.create(username="remote-perm-user")
        ct = DABContentType.objects.create(service="controller", model="inventory")
        RoleDefinition.objects.get_or_create(
            name="Test Remote Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment(
            "user",
            str(user.resource.ansible_id),
            "Test Remote Role",
            content_type="controller.inventory",
            object_id="12345",
        )
        assert cmd._create_assignment(assignment, "user") is True

    def test_content_object_not_found_returns_false(self):
        """When the content object's ansible_id doesn't match any Resource, return False
        with a message that says 'content object' (not ambiguous 'object').

        Uses Organization content type so the code enters the org/team branch
        where Resource lookup by ansible_id is performed.
        """
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="obj-notfound-user")
        org = Organization.objects.create(name="obj-notfound-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(
            name="Test ObjNotFound Role",
            defaults={"managed": False, "content_type": ct},
        )

        fake_obj_id = str(uuid.uuid4())
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment(
            "user",
            str(user.resource.ansible_id),
            "Test ObjNotFound Role",
            content_type="shared.organization",
            object_ansible_id=fake_obj_id,
        )
        assert cmd._create_assignment(assignment, "user") is False
        msg = cmd.stderr.write.call_args[0][0]
        assert f"Unable to find content object with ansible_id {fake_obj_id}" in msg
        assert "role 'Test ObjNotFound Role'" in msg

    def test_give_permission_failure_includes_all_identifiers(self):
        """A give_permission failure includes actor, role, and object identifiers
        in the error message so operators can identify which assignment failed at scale."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="fail-perm-user")
        rd, _ = RoleDefinition.objects.get_or_create(name="Test Fail Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        actor_id = str(user.resource.ansible_id)
        assignment = _make_remote_assignment("user", actor_id, "Test Fail Role")

        with patch.object(rd, "give_global_permission", side_effect=RuntimeError("DB constraint")):
            with patch.object(RoleDefinition.objects, "get", return_value=rd):
                result = cmd._create_assignment(assignment, "user")

        assert result is False
        cmd.stderr.write.assert_called_once()
        msg = cmd.stderr.write.call_args[0][0]
        assert "Unable to give permission for user assignment" in msg
        assert f"actor={actor_id}" in msg
        assert "role='Test Fail Role'" in msg

    def test_stale_actor_content_object_returns_false(self):
        """When the actor's Resource exists but its underlying object was
        deleted (stale generic FK), return False with a specific warning."""
        from ansible_base.resource_registry.models import Resource

        from aap_gateway_api.models import User

        user = User.objects.create(username="stale-actor-user")
        actor_ansible_id = str(user.resource.ansible_id)
        RoleDefinition.objects.get_or_create(name="Test Stale Actor Role", defaults={"managed": False})
        cmd = MigrateCommand()
        cmd.stdout = Mock()
        cmd.stderr = Mock()

        # Simulate stale FK: Resource exists but content_object returns None
        with patch.object(Resource.objects, "get") as mock_get:
            mock_resource = Mock()
            mock_resource.content_object = None
            mock_get.return_value = mock_resource
            result = cmd._create_assignment(
                {"user_ansible_id": actor_ansible_id, "role_definition": "Test Stale Actor Role", "content_type": "", "object_id": None},
                "user",
            )

        assert result is False

    def test_stale_org_content_object_returns_false(self):
        """When an org/team Resource exists but its content_object was
        deleted (stale generic FK), return False with a specific warning."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="stale-obj-user")
        org = Organization.objects.create(name="stale-obj-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(name="Test Stale Obj Role", defaults={"managed": False, "content_type": ct})

        cmd = MigrateCommand()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        obj_ansible_id = str(org.resource.ansible_id)

        # Delete the org so the Resource exists but content_object is None
        org.delete()
        result = cmd._create_assignment(
            {
                "user_ansible_id": str(user.resource.ansible_id),
                "role_definition": "Test Stale Obj Role",
                "content_type": "shared.organization",
                "object_ansible_id": obj_ansible_id,
                "object_id": None,
            },
            "user",
        )

        assert result is False


# =============================================================================
# _raise_fetch_error
# =============================================================================


class TestRaiseFetchError:
    """Tests for HTTP error handling with response body capture."""

    def test_includes_response_body(self):
        """Response body is included in the RuntimeError message."""
        resp = Mock(status_code=500)
        resp.text = "Internal Server Error: connection pool exhausted"

        with pytest.raises(RuntimeError, match="connection pool exhausted"):
            MigrateCommand._raise_fetch_error(resp, "user", 3)

    def test_handles_missing_response_text(self):
        """If response.text raises, the error still contains the status code."""
        resp = Mock(status_code=502)
        type(resp).text = property(lambda self: (_ for _ in ()).throw(AttributeError("no text")))

        with pytest.raises(RuntimeError, match="HTTP 502"):
            MigrateCommand._raise_fetch_error(resp, "team", 1)


# =============================================================================
# _get_role_definitions_to_exclude
# =============================================================================


class TestGetRoleDefinitionsToExclude:
    """Tests for per-service role exclusion filtering.

    Controller is authoritative for shared roles (Org Admin, Platform
    Auditor, etc.), so Hub and EDA exclude these roles to prevent
    duplicate or conflicting assignments.
    """

    def test_controller_excludes_nothing(self):
        """Controller migrates all roles — it's the authority for shared roles."""
        result = MigrateCommand._get_role_definitions_to_exclude("controller")
        assert result == []

    def test_hub_excludes_shared_except_team_member(self):
        """Hub excludes most shared roles but keeps Team Member."""
        result = MigrateCommand._get_role_definitions_to_exclude("hub")
        assert "Team Member" not in result
        assert "Organization Admin" in result
        assert "Platform Auditor" in result

    def test_eda_excludes_all_shared(self):
        """EDA excludes all five shared roles."""
        result = MigrateCommand._get_role_definitions_to_exclude("eda")
        assert "Team Member" in result
        assert "Organization Admin" in result
        assert "Platform Auditor" in result
        assert "Team Admin" in result
        assert "Organization Member" in result

    def test_unknown_service_excludes_all_shared(self):
        """Unknown service types default to excluding all shared roles (safe default)."""
        result = MigrateCommand._get_role_definitions_to_exclude("unknown")
        assert len(result) == 5
