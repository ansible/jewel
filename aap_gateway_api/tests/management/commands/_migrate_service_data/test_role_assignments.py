"""Tests for RoleAssignmentsMixin: TestPaginateAndCreate, TestMigrateRoleAssignments,
TestBulkResolveAndCreatePage, TestRaiseFetchError, TestGetRoleDefinitionsToExclude,
and integration tests for role assignment migration with live services.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.models import RemoteObject, RoleTeamAssignment, RoleUserAssignment
from django.core.management import call_command

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore
from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import assert_all_resources_synced, kill_test_service, launch_test_service

try:
    from ansible_base.rbac.models import RoleDefinition
except ImportError:
    pass


def _make_api_response(results, count=None, has_next=False):
    """Build a mock API response with proper status_code and JSON body."""
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
    """Build a dict matching the service API assignment response format."""
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


def _user_assignment_exists(username, role_definition_name, object_name) -> bool:
    """Helper to check if an assignment exists in gateway post-migration"""
    assignment = RoleUserAssignment.objects.filter(user__username=username, role_definition__name=role_definition_name).first()
    if assignment:
        if object_name is not None:
            return assignment.content_object.name == object_name  # type: ignore
        else:
            return assignment.content_object is None
    else:
        return False


# =============================================================================
# TestPaginateAndCreate
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
        cursor = CursorStore("test-svc", "user")
        empty_resp = _make_api_response([])
        list_fn = Mock(side_effect=[resp, empty_resp])

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(2, set())):
            created, obj_roles = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        new_cursor = CursorStore("test-svc", "user")
        assert new_cursor.last_pk == 2

    def test_cursor_applied_to_filters(self):
        """When cursor has a non-zero last_pk, id__gt is added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        seed = CursorStore("test-svc-filter", "user")
        seed.advance(100)
        cursor = CursorStore("test-svc-filter", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert call_filters["id__gt"] == "100"
        assert call_filters["order_by"] == "id"

    def test_cursor_zero_in_filters_when_fresh(self):
        """When cursor is at 0, id__gt is set to '0' in filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-zero", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert call_filters["id__gt"] == "0"

    def test_cursor_advances_per_page(self):
        """Cursor is advanced in DB after each page for crash safety."""
        page1 = _make_api_response([_make_remote_assignment("user", "u1", "Role1", pk=10)], has_next=True)
        page2 = _make_api_response([_make_remote_assignment("user", "u2", "Role1", pk=20)])
        empty = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-pages", "user")
        list_fn = Mock(side_effect=[page1, page2, empty])

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(1, set())):
            created, obj_roles = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 2
        assert cursor.last_pk == 0
        new_cursor = CursorStore("test-svc-pages", "user")
        assert new_cursor.last_pk == 20

    def test_empty_result_no_cursor_change(self):
        """When API returns 0 results, cursor stays unchanged."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        seed = CursorStore("test-svc-empty", "user")
        seed.advance(50)
        cursor = CursorStore("test-svc-empty", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_bulk_resolve_and_create_page") as mock_bulk:
            created, obj_roles = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 0
        mock_bulk.assert_not_called()
        new_cursor = CursorStore("test-svc-empty", "user")
        assert new_cursor.last_pk == 50

    def test_http_error_raises_immediately_with_body_preview(self):
        """HTTP error raises RuntimeError immediately with response body preview."""
        error_resp = Mock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error: database connection lost"

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-err", "user")
        list_fn = Mock(return_value=error_resp)

        with pytest.raises(RuntimeError, match="Failed to fetch user assignments page 0: HTTP 500"):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert list_fn.call_count == 1

    def test_http_error_mid_pagination_saves_cursor(self):
        """HTTP error on page 2: page 1 done, cursor saved at page 1's last PK."""
        page1 = _make_api_response([_make_remote_assignment("user", "u1", "Role1", pk=10)], has_next=True)
        error_resp = Mock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-mid", "user")
        list_fn = Mock(side_effect=[page1, error_resp])

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(1, set())):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

        new_cursor = CursorStore("test-svc-mid", "user")
        assert new_cursor.last_pk == 10

    def test_missing_pk_stops_pagination(self):
        """If the API returns an assignment without an 'id' field, pagination stops gracefully."""
        resp = _make_api_response([{"user_ansible_id": "u1", "role_definition": "Role1"}])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-nopk", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(1, set())):
            created, obj_roles = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 1
        assert obj_roles == set()

    def test_role_exclusion_filter_applied(self):
        """Role exclusion filter is passed to the API when non-empty."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-excl", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", ["Platform Auditor", "Organization Admin"], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "not__role_definition__name__in" in call_filters

    def test_multi_page_snapshot_prevents_skipping(self):
        """Verify that id__gt filter uses the sliding window value correctly."""
        page1 = _make_api_response([_make_remote_assignment("user", "u1", "Role1", pk=10)], has_next=True)
        page2 = _make_api_response([_make_remote_assignment("user", "u2", "Role1", pk=20)])
        empty = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-snapshot", "user")

        captured_id_gts = []
        pages = iter([page1, page2, empty])

        def capture_filters(**kwargs):
            captured_id_gts.append(kwargs["filters"]["id__gt"])
            return next(pages)

        list_fn = Mock(side_effect=capture_filters)

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(1, set())):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert captured_id_gts[0] == "0"
        assert captured_id_gts[1] == "10"

        new_cursor = CursorStore("test-svc-snapshot", "user")
        assert new_cursor.last_pk == 20

    def test_deletion_during_pagination_does_not_skip_items(self):
        """Sliding window using id__gt is stable against mid-run deletions."""
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", pk=5),
                _make_remote_assignment("user", "u2", "Role1", pk=10),
            ],
            has_next=True,
        )
        # Between pages, items with lower PKs "disappear" -- doesn't matter
        # because we use id__gt=10 (last PK from page 1)
        page2 = _make_api_response(
            [
                _make_remote_assignment("user", "u3", "Role1", pk=15),
                _make_remote_assignment("user", "u4", "Role1", pk=20),
            ],
            has_next=True,
        )
        page3 = _make_api_response(
            [
                _make_remote_assignment("user", "u5", "Role1", pk=25),
            ],
        )
        empty = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-deletion", "user")

        captured_id_gts = []
        pages = iter([page1, page2, page3, empty])

        def capture_filters(**kwargs):
            captured_id_gts.append(kwargs["filters"]["id__gt"])
            return next(pages)

        list_fn = Mock(side_effect=capture_filters)

        with patch.object(cmd, "_bulk_resolve_and_create_page", return_value=(1, set())):
            created, obj_roles = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert list_fn.call_count == 4
        assert created == 3  # 1 per page from mock

        # Verify sliding window: page1 id__gt=0, page2 id__gt=10, page3 id__gt=20
        assert captured_id_gts[0] == "0"
        assert captured_id_gts[1] == "10"
        assert captured_id_gts[2] == "20"

        new_cursor = CursorStore("test-svc-deletion", "user")
        assert new_cursor.last_pk == 25


# =============================================================================
# TestMigrateRoleAssignments
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

        with patch.object(cmd, "_paginate_and_create", return_value=(3, set())) as mock_paginate:
            cmd.migrate_role_assignments("controller", "controller")

        assert mock_paginate.call_count == 2
        call_types = [call[0][1] for call in mock_paginate.call_args_list]
        assert call_types == ["user", "team"]

    def test_creates_cursors_per_service(self):
        """Each service gets its own cursor records in the DB."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", return_value=(0, set())):
            cmd.migrate_role_assignments("controller", "controller")

        user_cursor = CursorStore("controller", "user")
        team_cursor = CursorStore("controller", "team")
        assert user_cursor.last_pk == 0
        assert team_cursor.last_pk == 0

    def test_http_failure_propagates(self):
        """RuntimeError from _paginate_and_create propagates to fail the service."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", side_effect=RuntimeError("HTTP 500")):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                cmd.migrate_role_assignments("controller", "controller")

    def test_no_drift_completes_normally(self):
        """When migration completes successfully, completion message is logged."""
        cmd = self._make_cmd()

        with patch.object(cmd, "_paginate_and_create", return_value=(5, set())):
            cmd.migrate_role_assignments("controller", "controller")

        cmd.stdout.write.assert_any_call("Role assignment migration for controller completed (10 total created)")

    def test_rbac_cache_rebuilt_when_object_roles_exist(self):
        """RBAC cache is rebuilt with union of object roles from both user and team calls."""
        cmd = self._make_cmd()
        mock_user_or = Mock()
        mock_team_or = Mock()

        with (
            patch.object(cmd, "_paginate_and_create", side_effect=[(5, {mock_user_or}), (4, {mock_team_or})]),
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_team_member_roles") as mock_team,
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_object_role_permissions") as mock_perms,
        ):
            cmd.migrate_role_assignments("controller", "controller")

        mock_team.assert_called_once()
        mock_perms.assert_called_once()
        call_kwargs = mock_perms.call_args[1]
        assert call_kwargs["object_roles"] == {mock_user_or, mock_team_or}

    def test_rbac_cache_team_member_roles_called_for_global_only(self):
        """compute_team_member_roles is called even when only global assignments are created."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=(3, set())),
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_team_member_roles") as mock_team,
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_object_role_permissions") as mock_perms,
        ):
            cmd.migrate_role_assignments("controller", "controller")

        mock_team.assert_called_once()
        mock_perms.assert_not_called()

    def test_rbac_cache_skipped_when_nothing_created(self):
        """RBAC cache rebuild is skipped when no assignments are created."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=(0, set())),
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_team_member_roles") as mock_team,
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_object_role_permissions") as mock_perms,
        ):
            cmd.migrate_role_assignments("controller", "controller")

        mock_team.assert_not_called()
        mock_perms.assert_not_called()

    def test_rbac_cache_rebuilt_even_on_exception(self):
        """RBAC cache is rebuilt in finally block even when an exception occurs."""
        cmd = self._make_cmd()
        mock_or = Mock()

        with (
            patch.object(
                cmd,
                "_paginate_and_create",
                side_effect=[(1, {mock_or}), RuntimeError("HTTP 500")],
            ),
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_team_member_roles") as mock_team,
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.compute_object_role_permissions") as mock_perms,
        ):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                cmd.migrate_role_assignments("controller", "controller")

        mock_team.assert_called_once()
        mock_perms.assert_called_once()

    def test_cursor_store_receives_log_fn(self):
        """CursorStore is instantiated with log_fn=cmd._log."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=(0, set())),
            patch("aap_gateway_api.management.commands._migrate_service_data.role_assignments.CursorStore") as mock_cursor_cls,
        ):
            mock_cursor_cls.return_value = Mock(last_pk=0)
            cmd.migrate_role_assignments("controller", "controller")

        for call_obj in mock_cursor_cls.call_args_list:
            assert call_obj[1]["log_fn"] == cmd._log


# =============================================================================
# TestBulkResolveAndCreatePage
# =============================================================================


@pytest.mark.django_db
class TestBulkResolveAndCreatePage:
    def _make_cmd(self):
        cmd = MigrateCommand()
        cmd.client = Mock()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        return cmd

    def test_empty_results_returns_zero(self):
        """Empty results list returns (0, set())."""
        cmd = self._make_cmd()
        created, obj_roles = cmd._bulk_resolve_and_create_page([], "user")
        assert created == 0
        assert obj_roles == set()

    def test_missing_actor_id_skipped(self):
        """Assignment with user_ansible_id=None is skipped."""
        cmd = self._make_cmd()
        results = [_make_remote_assignment("user", None, "SomeRole", pk=1)]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 0
        assert obj_roles == set()

    def test_missing_role_name_skipped(self):
        """Assignment with role_definition=None is skipped."""
        cmd = self._make_cmd()
        results = [_make_remote_assignment("user", str(uuid.uuid4()), None, pk=1)]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 0
        assert obj_roles == set()

    def test_unknown_role_definition_warns(self):
        """Non-existent role definition produces a warning."""
        cmd = self._make_cmd()
        results = [_make_remote_assignment("user", str(uuid.uuid4()), "NonexistentRoleXYZ", pk=1)]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 0
        msg = cmd.stderr.write.call_args[0][0]
        assert "Unable to find role definition 'NonexistentRoleXYZ'" in msg

    def test_missing_actor_resource_warns(self):
        """Valid role but fake actor UUID produces a warning."""

        cmd = self._make_cmd()
        RoleDefinition.objects.get_or_create(name="Test Bulk Actor Role", defaults={"managed": False})
        fake_actor_id = str(uuid.uuid4())
        results = [_make_remote_assignment("user", fake_actor_id, "Test Bulk Actor Role", pk=1)]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 0
        msg = cmd.stderr.write.call_args[0][0]
        assert f"Unable to find user with ansible_id {fake_actor_id}" in msg

    def test_missing_object_resource_warns(self):
        """Valid actor but fake object UUID produces a warning."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="bulk-obj-missing-user")
        rd, _ = RoleDefinition.objects.get_or_create(name="Test Bulk Obj Role", defaults={"managed": False})
        fake_obj_id = str(uuid.uuid4())
        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Obj Role",
                pk=1,
                object_ansible_id=fake_obj_id,
            )
        ]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 0
        msg = cmd.stderr.write.call_args[0][0]
        assert f"Unable to find object with ansible_id {fake_obj_id}" in msg

    def test_global_assignment_created(self):
        """Global assignment (no object_ansible_id/object_id) creates successfully."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="bulk-global-user")
        RoleDefinition.objects.get_or_create(name="Test Bulk Global Role", defaults={"managed": False})

        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Global Role",
                pk=1,
            )
        ]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 1
        assert obj_roles == set()

    def test_object_assignment_created(self):
        """Object-scoped assignment creates successfully with non-empty object roles set."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="bulk-obj-user")
        org = Organization.objects.create(name="bulk-obj-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(
            name="Test Bulk Obj Assign Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Obj Assign Role",
                pk=1,
                content_type="shared.organization",
                object_ansible_id=str(org.resource.ansible_id),
            )
        ]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 1
        assert len(obj_roles) > 0

    def test_team_assignment_type(self):
        """Team assignment type uses RoleTeamAssignment model."""
        from aap_gateway_api.models import Organization, Team

        org = Organization.objects.create(name="bulk-team-org")
        team = Team.objects.create(name="bulk-team-actor", organization=org)
        RoleDefinition.objects.get_or_create(name="Test Bulk Team Role", defaults={"managed": False})

        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "team",
                str(team.resource.ansible_id),
                "Test Bulk Team Role",
                pk=1,
            )
        ]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "team")
        assert created == 1
        assert RoleTeamAssignment.objects.filter(team=team, role_definition__name="Test Bulk Team Role").exists()

    def test_mixed_global_and_object(self):
        """Mix of global and object-scoped assignments returns correct totals."""
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="bulk-mixed-user")
        org = Organization.objects.create(name="bulk-mixed-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(name="Test Bulk Mixed Global", defaults={"managed": False})
        RoleDefinition.objects.get_or_create(
            name="Test Bulk Mixed Obj",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Mixed Global",
                pk=1,
            ),
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Mixed Obj",
                pk=2,
                content_type="shared.organization",
                object_ansible_id=str(org.resource.ansible_id),
            ),
        ]
        created, obj_roles = cmd._bulk_resolve_and_create_page(results, "user")
        assert created == 2
        assert len(obj_roles) > 0

    def test_idempotent_via_ignore_conflicts(self):
        """Calling twice with the same data does not duplicate rows."""
        from aap_gateway_api.models import User

        user = User.objects.create(username="bulk-idempotent-user")
        RoleDefinition.objects.get_or_create(name="Test Bulk Idempotent Role", defaults={"managed": False})

        cmd = self._make_cmd()
        results = [
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Test Bulk Idempotent Role",
                pk=1,
            )
        ]
        created1, _ = cmd._bulk_resolve_and_create_page(results, "user")
        assert created1 == 1

        created2, _ = cmd._bulk_resolve_and_create_page(results, "user")
        assert created2 in {0, 1}
        assert RoleUserAssignment.objects.filter(user__username="bulk-idempotent-user").count() == 1


# =============================================================================
# TestCollectUniqueIds
# =============================================================================


class TestCollectUniqueIds:
    def test_extracts_all_fields(self):
        results = [
            {"user_ansible_id": "u1", "role_definition": "Role A", "object_ansible_id": "obj1"},
            {"user_ansible_id": "u2", "role_definition": "Role B", "object_ansible_id": "obj2"},
            {"user_ansible_id": "u1", "role_definition": "Role A", "object_ansible_id": None},
        ]
        role_names, actor_ids, object_ids = MigrateCommand._collect_unique_ids(results, "user_ansible_id")
        assert role_names == {"Role A", "Role B"}
        assert actor_ids == {"u1", "u2"}
        assert object_ids == {"obj1", "obj2"}

    def test_empty_results(self):
        role_names, actor_ids, object_ids = MigrateCommand._collect_unique_ids([], "user_ansible_id")
        assert role_names == set()
        assert actor_ids == set()
        assert object_ids == set()

    def test_skips_none_values(self):
        results = [
            {"user_ansible_id": None, "role_definition": None, "object_ansible_id": None},
        ]
        role_names, actor_ids, object_ids = MigrateCommand._collect_unique_ids(results, "user_ansible_id")
        assert role_names == set()
        assert actor_ids == set()
        assert object_ids == set()

    def test_team_actor_field(self):
        results = [
            {"team_ansible_id": "t1", "role_definition": "Role A", "object_ansible_id": None},
        ]
        role_names, actor_ids, object_ids = MigrateCommand._collect_unique_ids(results, "team_ansible_id")
        assert actor_ids == {"t1"}


# =============================================================================
# TestResolveSingleAssignment
# =============================================================================


@pytest.mark.django_db
class TestResolveSingleAssignment:
    def _make_cmd(self):
        cmd = MigrateCommand()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        return cmd

    def test_missing_actor_returns_none(self):
        cmd = self._make_cmd()
        item = {"user_ansible_id": None, "role_definition": "Some Role"}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {}, {}, {})
        assert result is None

    def test_missing_role_returns_none(self):
        cmd = self._make_cmd()
        item = {"user_ansible_id": "u1", "role_definition": None}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {}, {}, {})
        assert result is None

    def test_unknown_role_returns_none_and_warns(self):
        cmd = self._make_cmd()
        item = {"user_ansible_id": "u1", "role_definition": "FakeRole"}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {}, {}, {})
        assert result is None
        cmd.stderr.write.assert_called_once()
        assert "Unable to find role definition 'FakeRole'" in cmd.stderr.write.call_args[0][0]

    def test_unknown_actor_returns_none_and_warns(self):
        cmd = self._make_cmd()
        rd = Mock()
        item = {"user_ansible_id": "u-missing", "role_definition": "TestRole"}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {"TestRole": rd}, {}, {})
        assert result is None
        assert "Unable to find user with ansible_id u-missing" in cmd.stderr.write.call_args[0][0]

    def test_global_assignment_classified(self):
        cmd = self._make_cmd()
        rd = Mock(content_type_id=None)
        actor_resource = Mock(object_id=42)
        item = {"user_ansible_id": "u1", "role_definition": "TestRole", "object_ansible_id": None, "object_id": None}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {"TestRole": rd}, {"u1": actor_resource}, {})
        assert result[0] == "global"
        assert result[1][0] == 42

    def test_object_assignment_by_ansible_id(self):
        cmd = self._make_cmd()
        rd = Mock(content_type_id=5)
        actor_resource = Mock(object_id=42)
        obj_resource = Mock(object_id=99)
        item = {"user_ansible_id": "u1", "role_definition": "TestRole", "object_ansible_id": "obj1", "object_id": None}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {"TestRole": rd}, {"u1": actor_resource}, {"obj1": obj_resource})
        assert result[0] == "object"
        assert result[1][3] == str(99)

    def test_object_assignment_by_object_id(self):
        cmd = self._make_cmd()
        rd = Mock(content_type_id=5)
        actor_resource = Mock(object_id=42)
        item = {"user_ansible_id": "u1", "role_definition": "TestRole", "object_ansible_id": None, "object_id": "777"}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {"TestRole": rd}, {"u1": actor_resource}, {})
        assert result[0] == "object"
        assert result[1][3] == "777"

    def test_missing_object_resource_returns_none_and_warns(self):
        cmd = self._make_cmd()
        rd = Mock(content_type_id=5)
        actor_resource = Mock(object_id=42)
        item = {"user_ansible_id": "u1", "role_definition": "TestRole", "object_ansible_id": "missing-obj", "object_id": None}
        result = cmd._resolve_single_assignment(item, "user_ansible_id", "user", {"TestRole": rd}, {"u1": actor_resource}, {})
        assert result is None
        assert "Unable to find object with ansible_id missing-obj" in cmd.stderr.write.call_args[0][0]


# =============================================================================
# TestRaiseFetchError
# =============================================================================


class TestRaiseFetchError:
    def test_includes_response_body(self):
        resp = Mock(status_code=500)
        resp.text = "Internal Server Error: connection pool exhausted"

        with pytest.raises(RuntimeError, match="connection pool exhausted"):
            MigrateCommand._raise_fetch_error(resp, "user", 3)

    def test_handles_missing_response_text(self):
        resp = Mock(status_code=502)
        type(resp).text = property(lambda self: (_ for _ in ()).throw(AttributeError("no text")))

        with pytest.raises(RuntimeError, match="HTTP 502"):
            MigrateCommand._raise_fetch_error(resp, "team", 1)


# =============================================================================
# TestGetRoleDefinitionsToExclude
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


# =============================================================================
# Integration tests for role assignment migration with live services
# =============================================================================


@pytest.fixture
def migration_service_controller_roles(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(svc_route=service_api_route_controller, fixture="migration_tests_controller_roles")
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def migration_service_controller_roles_paginated(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(
        svc_route=service_api_route_controller,
        fixture="migration_tests_controller_roles_pagination",
        page_size=10,
    )
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def migration_service_controller_roles_duplicate_teams(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(
        svc_route=service_api_route_controller,
        fixture="migration_tests_controller_roles_duplicate_teams",
    )
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def migration_service_controller_roles_remoteobject(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_test_service(
        svc_route=service_api_route_controller,
        fixture="migration_tests_controller_roles_remoteobject",
    )
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def migration_service_hub_roles(patched_resource_client, service_api_route_hub, ensure_jwt_keys):
    proc = launch_test_service(
        svc_route=service_api_route_hub,
        fixture="migration_tests_hub_roles",
        svc_type="galaxy",
    )
    yield service_api_route_hub
    kill_test_service(proc)


@pytest.mark.django_db()
def test_controller_role_assignment_migration(migration_service_controller_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated"""
    service_client = patched_resource_client(service=migration_service_controller_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    assert_all_resources_synced(admin_api_client, migration_service_controller_roles, service_client)

    for assignment in (
        ('controller-organization-admin', 'Organization Admin', 'controller-admin-organization'),
        ('controller-organization-member', 'Organization Member', 'controller-member-organization'),
        ('controller-team-admin', 'Team Admin', 'controller-admin-team'),
        ('controller-team-member', 'Team Member', 'controller-member-team'),
        ('controller-platform-auditor', 'Platform Auditor', None),
        ('controller-dummy-user', 'controller-dummy-role', 'controller-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])


@pytest.mark.django_db()
def test_controller_role_assignment_migration_reinstall_is_noop(
    migration_service_controller_roles, admin_user, admin_api_client, patched_resource_client, capsys
):
    """Test that running migrate_service_data a second time is a no-op."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    patched_resource_client(service=migration_service_controller_roles, user=admin_user, raise_if_bad_request=True)
    call_command("migrate_service_data", username=admin_user.username)

    for assignment in (
        ('controller-organization-admin', 'Organization Admin', 'controller-admin-organization'),
        ('controller-organization-member', 'Organization Member', 'controller-member-organization'),
        ('controller-team-admin', 'Team Admin', 'controller-admin-team'),
        ('controller-team-member', 'Team Member', 'controller-member-team'),
        ('controller-platform-auditor', 'Platform Auditor', None),
        ('controller-dummy-user', 'controller-dummy-role', 'controller-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])

    user_assignment_count_after_first_run = RoleUserAssignment.objects.count()
    team_assignment_count_after_first_run = RoleTeamAssignment.objects.count()
    assert user_assignment_count_after_first_run > 0

    MigrateServiceDataHasRan.mark_migration_not_completed()
    capsys.readouterr()

    call_command("migrate_service_data", username=admin_user.username)

    assert RoleUserAssignment.objects.count() == user_assignment_count_after_first_run
    assert RoleTeamAssignment.objects.count() == team_assignment_count_after_first_run

    captured = capsys.readouterr()
    assert "0 assignments created" in captured.out


@pytest.mark.django_db()
def test_controller_role_assignment_migration_paginated(migration_service_controller_roles_paginated, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in controller are migrated with pagination"""
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='many-assignments-user').count() == 40


@pytest.mark.django_db()
def test_controller_role_assignment_migration_duplicate_team_names(
    migration_service_controller_roles_duplicate_teams, admin_user, admin_api_client, patched_resource_client
):
    """Test that role assignments are migrated when duplicate team names exist"""
    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='duplicate-teams-user').count() == 2


@pytest.mark.django_db()
def test_controller_role_assignment_remoteobject(migration_service_controller_roles_remoteobject, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments referencing remote objects are migrated"""
    assert RoleUserAssignment.objects.filter(user__username='test-user').count() == 0
    assert RoleTeamAssignment.objects.filter(team__name='test-team').count() == 0
    call_command("migrate_service_data", username=admin_user.username)
    assert RoleUserAssignment.objects.filter(user__username='test-user').count() == 1
    rd = RoleUserAssignment.objects.get(user__username='test-user').role_definition
    assert issubclass(rd.content_type.model_class(), RemoteObject)


@pytest.mark.django_db()
def test_hub_role_assignment_migration(migration_service_hub_roles, admin_user, admin_api_client, patched_resource_client):
    """Test that role assignments in hub are migrated"""
    service_client = patched_resource_client(service=migration_service_hub_roles, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    assert_all_resources_synced(admin_api_client, migration_service_hub_roles, service_client)

    for assignment in (
        ('hub-team-member', 'Team Member', 'hub-member-team'),
        ('hub-dummy-user', 'hub-dummy-role', 'hub-dummy-organization'),
    ):
        assert _user_assignment_exists(assignment[0], assignment[1], assignment[2])

    for assignment in (
        ('hub-organization-admin', 'Organization Admin', 'hub-admin-organization'),
        ('hub-organization-member', 'Organization Member', 'hub-member-organization'),
        ('hub-team-admin', 'Team Admin', 'hub-admin-team'),
    ):
        assert not _user_assignment_exists(assignment[0], assignment[1], assignment[2])


@pytest.mark.django_db()
def test_role_assignment_migration_skips_user_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {
            "count": 0,
            "results": [],
        }
        invalid_user_ansible_id = str(uuid.uuid4())
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "count": 1,
            "next": None,
            "results": [
                {
                    "id": 1,
                    "object_ansible_id": None,
                    "content_type": "",
                    "role_definition": "Platform Auditor",
                    "user_ansible_id": invalid_user_ansible_id,
                }
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"count": 0, "next": None, "results": []}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Unable to find user with ansible_id {invalid_user_ansible_id}" in captured.err


@pytest.mark.django_db()
def test_role_assignment_migration_skips_role_definition_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    from aap_gateway_api.models import User

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {
            "count": 0,
            "results": [],
        }
        test_user = User.objects.create(username='test-user')
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "count": 1,
            "next": None,
            "results": [
                {
                    "id": 1,
                    "object_ansible_id": None,
                    "content_type": "",
                    "role_definition": "INVALID ROLE DEFINITION",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"count": 0, "next": None, "results": []}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert "Unable to find role definition 'INVALID ROLE DEFINITION'" in captured.err


@pytest.mark.django_db()
def test_role_assignment_migration_skips_object_not_found(admin_user, capsys, service_api_route_controller, patched_resource_client):
    from aap_gateway_api.models import User

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {
            "count": 0,
            "results": [],
        }
        invalid_object_ansible_id = str(uuid.uuid4())
        test_user = User.objects.create(username='test-user')
        data_resp = Mock(status_code=200)
        data_resp.json.return_value = {
            "count": 1,
            "next": None,
            "results": [
                {
                    "id": 1,
                    "object_ansible_id": invalid_object_ansible_id,
                    "content_type": "shared.team",
                    "role_definition": "Team Member",
                    "user_ansible_id": test_user.resource.ansible_id,
                }
            ],
        }
        empty_resp = Mock(status_code=200)
        empty_resp.json.return_value = {"count": 0, "next": None, "results": []}
        mock_client.list_user_assignments.side_effect = [data_resp, empty_resp]
        mock_client.list_team_assignments.return_value = empty_resp
        mock_client_class.return_value = mock_client

        assert RoleUserAssignment.objects.count() == 0
        call_command("migrate_service_data", username=admin_user.username)
        assert RoleUserAssignment.objects.count() == 0

        captured = capsys.readouterr()
        assert f"Unable to find object with ansible_id {invalid_object_ansible_id}" in captured.err
