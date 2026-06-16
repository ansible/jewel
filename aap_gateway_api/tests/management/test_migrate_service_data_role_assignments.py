"""Tests for role assignment migration in the migrate_service_data command.

The migration uses a PK-based cursor to fetch only new assignments from
upstream services.  On each run, it queries with ``id__gt=<last_pk>&order_by=id``
so only assignments created since the last run are fetched.  The cursor is
advanced after each fully-processed page, providing crash safety.

give_permission is idempotent (uses get_or_create internally), so replaying
a partial page after a crash is safe.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.role_sync_utils import AssignmentTuple

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models.migrate_data import MigrateServiceDataLastRolePK


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
# MigrateServiceDataLastRolePK model
# =============================================================================


@pytest.mark.django_db
class TestMigrateServiceDataLastRolePK:
    def test_get_last_pk_creates_default_zero(self):
        """First call creates a cursor with last_pk=0."""
        cursor = MigrateServiceDataLastRolePK.get_last_pk("controller", "user")
        assert cursor.last_pk == 0

    def test_get_last_pk_returns_existing(self):
        """Subsequent calls return the same cursor object."""
        cursor1 = MigrateServiceDataLastRolePK.get_last_pk("controller", "user")
        cursor1.advance(100)
        cursor2 = MigrateServiceDataLastRolePK.get_last_pk("controller", "user")
        assert cursor2.last_pk == 100

    def test_advance_updates_pk(self):
        """advance() persists the new PK to the database."""
        cursor = MigrateServiceDataLastRolePK.get_last_pk("hub", "team")
        cursor.advance(42)
        cursor.refresh_from_db()
        assert cursor.last_pk == 42

    def test_unique_per_service_and_type(self):
        """Each (service_slug, assignment_type) pair gets its own cursor."""
        c1 = MigrateServiceDataLastRolePK.get_last_pk("controller", "user")
        c2 = MigrateServiceDataLastRolePK.get_last_pk("controller", "team")
        c3 = MigrateServiceDataLastRolePK.get_last_pk("hub", "user")
        c1.advance(10)
        c2.advance(20)
        c3.advance(30)
        assert MigrateServiceDataLastRolePK.get_last_pk("controller", "user").last_pk == 10
        assert MigrateServiceDataLastRolePK.get_last_pk("controller", "team").last_pk == 20
        assert MigrateServiceDataLastRolePK.get_last_pk("hub", "user").last_pk == 30


# =============================================================================
# _build_assignment_tuple
# =============================================================================


class TestBuildAssignmentTuple:
    def test_user_global_assignment(self):
        assignment = _make_remote_assignment("user", "user-uuid-1", "Platform Auditor")
        t = MigrateCommand._build_assignment_tuple(assignment, "user")
        assert t == AssignmentTuple(
            actor_ansible_id="user-uuid-1",
            ansible_id_or_pk=None,
            role_definition_name="Platform Auditor",
            assignment_type="user",
        )

    def test_team_global_assignment(self):
        assignment = _make_remote_assignment("team", "team-uuid-1", "Platform Auditor")
        t = MigrateCommand._build_assignment_tuple(assignment, "team")
        assert t == AssignmentTuple(
            actor_ansible_id="team-uuid-1",
            ansible_id_or_pk=None,
            role_definition_name="Platform Auditor",
            assignment_type="team",
        )

    def test_org_uses_ansible_id(self):
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
        assignment = {"role_definition": "Some Role", "user_ansible_id": None}
        assert MigrateCommand._build_assignment_tuple(assignment, "user") is None

    def test_missing_role_returns_none(self):
        assignment = {"user_ansible_id": "user-uuid-1", "role_definition": None}
        assert MigrateCommand._build_assignment_tuple(assignment, "user") is None


# =============================================================================
# _paginate_and_create — PK cursor pagination
#
# These tests verify the cursor-based pagination: each page is fetched with
# order_by=id and id__gt=<cursor.last_pk>, assignments are created per page,
# and the cursor is advanced after each fully-processed page.
# =============================================================================


@pytest.mark.django_db
class TestPaginateAndCreate:
    def _make_cmd(self):
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
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        cursor.refresh_from_db()
        assert cursor.last_pk == 2

    def test_cursor_applied_to_filters(self):
        """When cursor has a non-zero last_pk, id__gt is added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-filter", "user")
        cursor.advance(100)
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert call_filters["id__gt"] == "100"
        assert call_filters["order_by"] == "id"

    def test_cursor_not_in_filters_when_zero(self):
        """When cursor is at 0, id__gt is not added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-zero", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "id__gt" not in call_filters

    def test_cursor_advances_per_page(self):
        """Cursor is advanced after each fully-processed page, not just at the end."""
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
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-pages", "user")
        list_fn = Mock(side_effect=[page1, page2])

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        cursor.refresh_from_db()
        assert cursor.last_pk == 20

    def test_empty_result_no_cursor_change(self):
        """When API returns 0 results, cursor stays unchanged."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-empty", "user")
        cursor.advance(50)
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment_from_tuple") as mock_create:
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 0
        mock_create.assert_not_called()
        cursor.refresh_from_db()
        assert cursor.last_pk == 50

    def test_http_error_retries_then_raises(self):
        """HTTP errors are retried up to HTTP_RETRY_LIMIT times, then raise
        RuntimeError to fail the service (non-zero exit for installer retry)."""
        error_resp = Mock()
        error_resp.status_code = 500

        cmd = self._make_cmd()
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-err", "user")
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
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-mid", "user")
        # page1 succeeds, then all retries for page2 fail
        list_fn = Mock(side_effect=[page1] + [error_resp] * MigrateCommand.HTTP_RETRY_LIMIT)

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

        # Cursor saved at page 1's last PK — next run resumes from here
        cursor.refresh_from_db()
        assert cursor.last_pk == 10

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
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-retry", "user")
        # First call fails, retry succeeds
        list_fn = Mock(side_effect=[error_resp, success_resp])

        with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 1
        cursor.refresh_from_db()
        assert cursor.last_pk == 5

    def test_role_exclusion_filter_applied(self):
        """Role exclusion filter is passed to the API when non-empty."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = MigrateServiceDataLastRolePK.get_last_pk("test-svc-excl", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", ["Platform Auditor", "Organization Admin"], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "not__role_definition__name__in" in call_filters


# =============================================================================
# migrate_role_assignments — orchestration
# =============================================================================


@pytest.mark.django_db
class TestMigrateRoleAssignments:
    def _make_cmd(self):
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
        """Each service gets its own cursor records."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", return_value=0):
            cmd.migrate_role_assignments("controller", "controller")

        assert MigrateServiceDataLastRolePK.objects.filter(service_slug="controller", assignment_type="user").exists()
        assert MigrateServiceDataLastRolePK.objects.filter(service_slug="controller", assignment_type="team").exists()

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
    def test_missing_role_definition_returns_false(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        t = AssignmentTuple("user-uuid", "org-uuid", "NonexistentRole", "user")
        assert cmd._create_assignment_from_tuple(t) is False
        assert "Unable to find role definition NonexistentRole" in cmd.stderr.write.call_args[0][0]

    def test_missing_actor_resource_returns_false(self):
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
    def test_controller_excludes_nothing(self):
        result = MigrateCommand._get_role_definitions_to_exclude("controller")
        assert result == []

    def test_hub_excludes_shared_except_team_member(self):
        result = MigrateCommand._get_role_definitions_to_exclude("hub")
        assert "Team Member" not in result
        assert "Organization Admin" in result
        assert "Platform Auditor" in result

    def test_eda_excludes_all_shared(self):
        result = MigrateCommand._get_role_definitions_to_exclude("eda")
        assert "Team Member" in result
        assert "Organization Admin" in result
        assert "Platform Auditor" in result
        assert "Team Admin" in result
        assert "Organization Member" in result

    def test_unknown_service_excludes_all_shared(self):
        result = MigrateCommand._get_role_definitions_to_exclude("unknown")
        assert len(result) == 5
