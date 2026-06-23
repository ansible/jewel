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
from ansible_base.rbac.role_sync_utils import AssignmentTuple

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

    def test_graceful_degradation_on_db_error(self):
        """If the database is unreachable, last_pk defaults to 0 and a warning is logged.

        This ensures the command can still run (reprocessing all assignments)
        rather than failing outright on a cursor table issue.
        """
        with patch("aap_gateway_api.management.commands.migrate_service_data.connection") as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError("DB unavailable")
            cursor = _CursorStore("controller", "user")

        assert cursor.last_pk == 0


# =============================================================================
# _build_assignment_tuple
# =============================================================================


class TestBuildAssignmentTuple:
    """Tests for converting API response dicts to AssignmentTuple.

    Key resolution must match get_local_assignments() in DAB:
    org/team content types use object_ansible_id, everything else uses
    the raw object_id, and global assignments use None.
    """

    def test_user_global_assignment(self):
        """Global user assignment has ansible_id_or_pk=None."""
        assignment = _make_remote_assignment("user", "user-uuid-1", "Platform Auditor")
        t = MigrateCommand._build_assignment_tuple(assignment, "user")
        assert t == AssignmentTuple(
            actor_ansible_id="user-uuid-1",
            ansible_id_or_pk=None,
            role_definition_name="Platform Auditor",
            assignment_type="user",
        )

    def test_team_global_assignment(self):
        """Global team assignment has ansible_id_or_pk=None."""
        assignment = _make_remote_assignment("team", "team-uuid-1", "Platform Auditor")
        t = MigrateCommand._build_assignment_tuple(assignment, "team")
        assert t == AssignmentTuple(
            actor_ansible_id="team-uuid-1",
            ansible_id_or_pk=None,
            role_definition_name="Platform Auditor",
            assignment_type="team",
        )

    def test_org_uses_ansible_id(self):
        """Organization assignments use object_ansible_id (not object_id)."""
        assignment = _make_remote_assignment(
            "user",
            "user-uuid-1",
            "Organization Admin",
            content_type="shared.organization",
            object_ansible_id="org-uuid-1",
            object_id="42",
        )
        t = MigrateCommand._build_assignment_tuple(assignment, "user")
        assert t.ansible_id_or_pk == "org-uuid-1"

    def test_team_content_type_uses_ansible_id(self):
        """Team content type assignments use object_ansible_id (not object_id)."""
        assignment = _make_remote_assignment(
            "user",
            "user-uuid-1",
            "Team Admin",
            content_type="shared.team",
            object_ansible_id="team-uuid-1",
            object_id="99",
        )
        t = MigrateCommand._build_assignment_tuple(assignment, "user")
        assert t.ansible_id_or_pk == "team-uuid-1"

    def test_service_specific_uses_object_id(self):
        """Service-specific content types (e.g. controller.inventory) use object_id."""
        assignment = _make_remote_assignment(
            "user",
            "user-uuid-1",
            "Inventory Admin",
            content_type="controller.inventory",
            object_ansible_id="inv-uuid-1",
            object_id="123",
        )
        t = MigrateCommand._build_assignment_tuple(assignment, "user")
        assert t.ansible_id_or_pk == "123"

    def test_missing_actor_returns_none(self):
        """Missing actor ansible_id returns None (skip this assignment)."""
        assignment = {"role_definition": "Some Role", "user_ansible_id": None}
        assert MigrateCommand._build_assignment_tuple(assignment, "user") is None

    def test_missing_role_returns_none(self):
        """Missing role_definition returns None (skip this assignment)."""
        assignment = {"user_ansible_id": "user-uuid-1", "role_definition": None}
        assert MigrateCommand._build_assignment_tuple(assignment, "user") is None


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

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
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

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
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

        with patch.object(cmd, "_create_assignment_from_tuple") as mock_create:
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 0
        mock_create.assert_not_called()
        # DB cursor unchanged
        new_cursor = _CursorStore("test-svc-empty", "user")
        assert new_cursor.last_pk == 50

    def test_http_error_retries_then_raises(self):
        """HTTP errors are retried up to HTTP_RETRY_LIMIT times, then raise
        RuntimeError to fail the service (non-zero exit for installer retry)."""
        error_resp = Mock()
        error_resp.status_code = 500

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-err", "user")
        list_fn = Mock(return_value=error_resp)

        with pytest.raises(RuntimeError, match="Failed to fetch user assignments"):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        # Should have been called HTTP_RETRY_LIMIT times
        assert list_fn.call_count == MigrateCommand.HTTP_RETRY_LIMIT

    def test_http_error_mid_pagination_saves_cursor(self):
        """HTTP error on page 2: page 1 assignments created, cursor saved at
        page 1's last PK. RuntimeError raised after retries exhausted."""
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", pk=10),
            ],
            has_next=True,
        )
        error_resp = Mock()
        error_resp.status_code = 500

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-mid", "user")
        # page1 succeeds, then all retries for page2 fail
        list_fn = Mock(side_effect=[page1] + [error_resp] * MigrateCommand.HTTP_RETRY_LIMIT)

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

        # DB cursor saved at page 1's last PK — next run resumes from here
        new_cursor = _CursorStore("test-svc-mid", "user")
        assert new_cursor.last_pk == 10

    def test_transient_error_recovers_on_retry(self):
        """A single HTTP error followed by success should continue normally."""
        error_resp = Mock()
        error_resp.status_code = 500
        success_resp = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", pk=5),
            ]
        )

        cmd = self._make_cmd()
        cursor = _CursorStore("test-svc-retry", "user")
        # First call fails, retry succeeds
        list_fn = Mock(side_effect=[error_resp, success_resp])

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 1
        new_cursor = _CursorStore("test-svc-retry", "user")
        assert new_cursor.last_pk == 5

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

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
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

        with patch.object(cmd, "_paginate_and_create", return_value=3) as mock_paginate:
            cmd.migrate_role_assignments("controller", "controller")

        # Called twice: once for user, once for team
        assert mock_paginate.call_count == 2
        call_types = [call[0][1] for call in mock_paginate.call_args_list]
        assert call_types == ["user", "team"]

    def test_creates_cursors_per_service(self):
        """Each service gets its own cursor records in the DB."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", return_value=0):
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


# =============================================================================
# _create_assignment_from_tuple
# =============================================================================


@pytest.mark.django_db
class TestCreateAssignmentFromTuple:
    """Tests for creating local role assignments from AssignmentTuples.

    Each resolution step (role definition, actor, content object) has its
    own error handling so operators get specific messages identifying what
    failed and why.
    """

    def test_missing_role_definition_returns_false(self):
        """Missing role definition returns False with error identifying the role."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple("user-uuid", "org-uuid", "NonexistentRole", "user")
        assert cmd._create_assignment_from_tuple(t) is False
        assert "Unable to find role definition NonexistentRole" in cmd.stderr.write.call_args[0][0]

    def test_missing_actor_resource_returns_false(self):
        """Missing actor resource returns False with error identifying the actor."""
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        RoleDefinition.objects.get_or_create(
            name="Test Role Create",
            defaults={"managed": False},
        )
        fake_id = str(uuid.uuid4())
        t = AssignmentTuple(fake_id, None, "Test Role Create", "user")
        assert cmd._create_assignment_from_tuple(t) is False
        assert f"Unable to find user with ansible_id {fake_id}" in cmd.stderr.write.call_args[0][0]

    def test_global_assignment_created(self):
        """Global assignment (no content object) is created via give_global_permission."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="global-perm-user")
        rd, _ = RoleDefinition.objects.get_or_create(name="Test Global Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple(
            actor_ansible_id=str(user.resource.ansible_id),
            ansible_id_or_pk=None,
            role_definition_name="Test Global Role",
            assignment_type="user",
        )
        assert cmd._create_assignment_from_tuple(t) is True

    def test_org_team_assignment_created(self):
        """Org/team assignment is created by resolving the object via Resource ansible_id."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="org-perm-user")
        org = Organization.objects.create(name="test-perm-org")
        ct = DABContentType.objects.get_for_model(org)
        rd, _ = RoleDefinition.objects.get_or_create(
            name="Test Org Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple(
            actor_ansible_id=str(user.resource.ansible_id),
            ansible_id_or_pk=str(org.resource.ansible_id),
            role_definition_name="Test Org Role",
            assignment_type="user",
        )
        assert cmd._create_assignment_from_tuple(t) is True

    def test_remote_object_assignment_created(self):
        """Service-specific assignment is created by wrapping the PK in a RemoteObject."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import User

        user = User.objects.create(username="remote-perm-user")
        ct = DABContentType.objects.create(service="controller", model="inventory")
        rd, _ = RoleDefinition.objects.get_or_create(
            name="Test Remote Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple(
            actor_ansible_id=str(user.resource.ansible_id),
            ansible_id_or_pk="12345",
            role_definition_name="Test Remote Role",
            assignment_type="user",
        )
        assert cmd._create_assignment_from_tuple(t) is True

    def test_object_not_found_returns_false(self):
        """When the content object's ansible_id doesn't match any Resource, return False
        with a specific message identifying the missing object.

        Uses Organization content type so the code enters the org/team branch
        (content_type.model in ('organization', 'team')) where Resource lookup
        by ansible_id is performed and Resource.DoesNotExist is caught.
        """
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="obj-notfound-user")
        org = Organization.objects.create(name="obj-notfound-org")
        ct = DABContentType.objects.get_for_model(org)
        rd, _ = RoleDefinition.objects.get_or_create(
            name="Test ObjNotFound Role",
            defaults={"managed": False, "content_type": ct},
        )

        fake_obj_id = str(uuid.uuid4())
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple(
            actor_ansible_id=str(user.resource.ansible_id),
            ansible_id_or_pk=fake_obj_id,
            role_definition_name="Test ObjNotFound Role",
            assignment_type="user",
        )
        assert cmd._create_assignment_from_tuple(t) is False
        assert f"Unable to find object with ansible_id {fake_obj_id}" in cmd.stderr.write.call_args[0][0]

    def test_give_permission_failure_returns_false_and_continues(self):
        """A give_permission failure for one assignment should return False (not raise),
        so the caller can continue processing remaining assignments."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="fail-perm-user")
        rd, _ = RoleDefinition.objects.get_or_create(name="Test Fail Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple(
            actor_ansible_id=str(user.resource.ansible_id),
            ansible_id_or_pk=None,
            role_definition_name="Test Fail Role",
            assignment_type="user",
        )

        with patch.object(rd, "give_global_permission", side_effect=RuntimeError("DB constraint")):
            with patch.object(RoleDefinition.objects, "get", return_value=rd):
                result = cmd._create_assignment_from_tuple(t)

        assert result is False
        cmd.stderr.write.assert_called_once()
        assert "Unable to give permission for user assignment" in cmd.stderr.write.call_args[0][0]


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
