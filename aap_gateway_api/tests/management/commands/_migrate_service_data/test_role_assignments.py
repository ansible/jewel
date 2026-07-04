"""Tests for RoleAssignmentsMixin: TestPaginateAndCreate, TestMigrateRoleAssignments,
TestCreateAssignment, TestRaiseFetchError, TestGetRoleDefinitionsToExclude,
and integration tests for role assignment migration with live services.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.models import RemoteObject, RoleTeamAssignment, RoleUserAssignment
from ansible_base.resource_registry.models import Resource
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
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

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

    def test_cursor_not_in_filters_when_zero(self):
        """When cursor is at 0, id__gt is not added to filters."""
        resp = _make_api_response([])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-zero", "user")
        list_fn = Mock(return_value=resp)

        cmd._paginate_and_create(list_fn, "user", [], cursor)

        call_filters = list_fn.call_args[1]["filters"]
        assert "id__gt" not in call_filters

    def test_cursor_advances_per_page(self):
        """Cursor is advanced in DB after each page for crash safety."""
        page1 = _make_api_response([_make_remote_assignment("user", "u1", "Role1", pk=10)], has_next=True)
        page2 = _make_api_response([_make_remote_assignment("user", "u2", "Role1", pk=20)])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-pages", "user")
        list_fn = Mock(side_effect=[page1, page2])

        with patch.object(cmd, "_create_assignment", return_value=True):
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

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

        with patch.object(cmd, "_create_assignment") as mock_create:
            created = cmd._paginate_and_create(list_fn, "user", [], cursor)

        assert created == 0
        mock_create.assert_not_called()
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

        with pytest.raises(RuntimeError, match="Failed to fetch user assignments page 1: HTTP 500"):
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

        with patch.object(cmd, "_create_assignment", return_value=True):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

        new_cursor = CursorStore("test-svc-mid", "user")
        assert new_cursor.last_pk == 10

    def test_missing_pk_raises_runtime_error(self):
        """If the API returns an assignment without an 'id' field, raise RuntimeError."""
        resp = _make_api_response([{"user_ansible_id": "u1", "role_definition": "Role1"}])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-nopk", "user")
        list_fn = Mock(return_value=resp)

        with patch.object(cmd, "_create_assignment", return_value=True):
            with pytest.raises(RuntimeError, match="without 'id' field"):
                cmd._paginate_and_create(list_fn, "user", [], cursor)

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
        """Verify that id__gt filter uses the snapshot value, not the advancing DB cursor."""
        page1 = _make_api_response([_make_remote_assignment("user", "u1", "Role1", pk=10)], has_next=True)
        page2 = _make_api_response([_make_remote_assignment("user", "u2", "Role1", pk=20)])

        cmd = self._make_cmd()
        cursor = CursorStore("test-svc-snapshot", "user")
        list_fn = Mock(side_effect=[page1, page2])

        with patch.object(cmd, "_create_assignment", return_value=True):
            cmd._paginate_and_create(list_fn, "user", [], cursor)

        page1_filters = list_fn.call_args_list[0][1]["filters"]
        page2_filters = list_fn.call_args_list[1][1]["filters"]
        assert "id__gt" not in page1_filters
        assert "id__gt" not in page2_filters

        new_cursor = CursorStore("test-svc-snapshot", "user")
        assert new_cursor.last_pk == 20


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

        with (
            patch.object(cmd, "_paginate_and_create", return_value=3) as mock_paginate,
            patch.object(cmd, "_check_for_drift", return_value=False),
        ):
            cmd.migrate_role_assignments("controller", "controller")

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

    def test_drift_detected_raises_runtime_error(self):
        """When post-run drift check detects new assignments, RuntimeError is raised."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=5),
            patch.object(cmd, "_check_for_drift", return_value=True),
        ):
            with pytest.raises(RuntimeError, match="concurrent modifications were detected"):
                cmd.migrate_role_assignments("controller", "controller")

    def test_no_drift_completes_normally(self):
        """When post-run drift check finds no new items, method completes without raising."""
        cmd = self._make_cmd()

        with (
            patch.object(cmd, "_paginate_and_create", return_value=5),
            patch.object(cmd, "_check_for_drift", return_value=False),
        ):
            cmd.migrate_role_assignments("controller", "controller")

        cmd.stdout.write.assert_any_call("Role assignment migration for controller completed (10 total created)")

    def test_check_for_drift_queries_beyond_cursor(self):
        """_check_for_drift loads a fresh cursor from DB and asks the API."""
        cmd = self._make_cmd()

        seed = CursorStore("drift-check-svc", "user")
        seed.advance(100)

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

        seed = CursorStore("drift-empty-svc", "user")
        seed.advance(50)

        no_drift_resp = Mock()
        no_drift_resp.status_code = 200
        no_drift_resp.json.return_value = {"count": 0}
        list_fn = Mock(return_value=no_drift_resp)

        assert cmd._check_for_drift(list_fn, "user", "drift-empty-svc") is False

    def test_check_for_drift_skips_when_cursor_is_zero(self):
        """_check_for_drift skips the API call when cursor is at 0."""
        cmd = self._make_cmd()
        list_fn = Mock()

        assert cmd._check_for_drift(list_fn, "user", "drift-zero-svc") is False
        list_fn.assert_not_called()

    def test_check_for_drift_returns_false_on_api_error(self):
        """If the drift check API call fails, assume no drift and continue."""
        cmd = self._make_cmd()

        seed = CursorStore("drift-err-svc", "user")
        seed.advance(50)

        list_fn = Mock(side_effect=RuntimeError("connection refused"))

        assert cmd._check_for_drift(list_fn, "user", "drift-err-svc") is False


# =============================================================================
# TestCreateAssignment
# =============================================================================


@pytest.mark.django_db
class TestCreateAssignment:
    def test_missing_actor_returns_false_silently(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = {"role_definition": "Some Role", "user_ansible_id": None}
        assert cmd._create_assignment(assignment, "user") is False
        cmd.stderr.write.assert_not_called()

    def test_missing_role_returns_false_silently(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = {"user_ansible_id": "user-uuid-1", "role_definition": None}
        assert cmd._create_assignment(assignment, "user") is False
        cmd.stderr.write.assert_not_called()

    def test_missing_role_definition_returns_false(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("user", "user-uuid", "NonexistentRole")
        assert cmd._create_assignment(assignment, "user") is False
        msg = cmd.stderr.write.call_args[0][0]
        assert "Unable to find role definition 'NonexistentRole'" in msg
        assert "actor user-uuid" in msg

    def test_missing_actor_resource_returns_false(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        RoleDefinition.objects.get_or_create(name="Test Role Create", defaults={"managed": False})
        fake_id = str(uuid.uuid4())
        assignment = _make_remote_assignment("user", fake_id, "Test Role Create")
        assert cmd._create_assignment(assignment, "user") is False
        msg = cmd.stderr.write.call_args[0][0]
        assert f"Unable to find user with ansible_id {fake_id}" in msg
        assert "role 'Test Role Create'" in msg

    def test_global_assignment_created(self):
        from aap_gateway_api.models import User

        user = User.objects.create(username="global-perm-user")
        RoleDefinition.objects.get_or_create(name="Test Global Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("user", str(user.resource.ansible_id), "Test Global Role")
        assert cmd._create_assignment(assignment, "user") is True

    def test_org_assignment_created(self):
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="org-perm-user")
        org = Organization.objects.create(name="test-perm-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(name="Test Org Role", defaults={"managed": False, "content_type": ct})

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
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, Team, User

        user = User.objects.create(username="team-perm-user")
        org = Organization.objects.create(name="test-team-perm-org")
        team = Team.objects.create(name="test-perm-team", organization=org)
        ct = DABContentType.objects.get_for_model(team)
        RoleDefinition.objects.get_or_create(name="Test Team Role", defaults={"managed": False, "content_type": ct})

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
        from aap_gateway_api.models import Organization, Team

        org = Organization.objects.create(name="team-actor-org")
        team = Team.objects.create(name="team-actor-team", organization=org)
        RoleDefinition.objects.get_or_create(name="Test Team Actor Role", defaults={"managed": False})

        cmd = MigrateCommand()
        cmd.stderr = Mock()
        assignment = _make_remote_assignment("team", str(team.resource.ansible_id), "Test Team Actor Role")
        assert cmd._create_assignment(assignment, "team") is True

    def test_remote_object_assignment_created(self):
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import User

        user = User.objects.create(username="remote-perm-user")
        ct = DABContentType.objects.create(service="controller", model="inventory")
        RoleDefinition.objects.get_or_create(name="Test Remote Role", defaults={"managed": False, "content_type": ct})

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
        from aap_gateway_api.models import User

        user = User.objects.create(username="stale-actor-user")
        actor_ansible_id = str(user.resource.ansible_id)
        RoleDefinition.objects.get_or_create(name="Test Stale Actor Role", defaults={"managed": False})
        cmd = MigrateCommand()
        cmd.stdout = Mock()
        cmd.stderr = Mock()

        with patch.object(Resource.objects, "get") as mock_get:
            mock_resource = Mock()
            mock_resource.content_object = None
            mock_get.return_value = mock_resource
            result = cmd._create_assignment(
                {
                    "user_ansible_id": actor_ansible_id,
                    "role_definition": "Test Stale Actor Role",
                    "content_type": "",
                    "object_id": None,
                },
                "user",
            )

        assert result is False

    def test_stale_org_content_object_returns_false(self):
        from ansible_base.rbac.models import DABContentType

        from aap_gateway_api.models import Organization, User

        user = User.objects.create(username="stale-obj-user")
        org = Organization.objects.create(name="stale-obj-org")
        ct = DABContentType.objects.get_for_model(org)
        RoleDefinition.objects.get_or_create(
            name="Test Stale Obj Role",
            defaults={"managed": False, "content_type": ct},
        )

        cmd = MigrateCommand()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        obj_ansible_id = str(org.resource.ansible_id)

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
        assert f"Unable to find content object with ansible_id {invalid_object_ansible_id}" in captured.err
