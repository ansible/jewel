import uuid
from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.assignment_utils import AssignmentTuple
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.management.commands.migrate_service_data import _RemoteFetchResult


def _make_api_response(results, count=None, has_next=False):
    """Build a mock API response with the given results."""
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
    return d


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
# _fetch_remote_assignment_set
# =============================================================================


class TestFetchRemoteAssignmentSet:
    def _make_cmd_with_client(self, user_responses, team_responses):
        """Create a Command with a mocked client returning the given page sequences."""
        cmd = MigrateCommand()
        cmd.client = Mock()
        cmd.client.list_user_assignments.side_effect = user_responses
        cmd.client.list_team_assignments.side_effect = team_responses
        return cmd

    def test_single_page_no_drift(self):
        user_resp = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Org Admin", "shared.organization", object_ansible_id="org1"),
            ],
            count=1,
        )
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([user_resp], [team_resp])
        result = cmd._fetch_remote_assignment_set("controller")

        assert len(result.assignments) == 1
        assert not result.count_drifted

    def test_multi_page_no_drift(self):
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", "controller.inventory", object_id="1"),
            ],
            count=2,
            has_next=True,
        )
        page2 = _make_api_response(
            [
                _make_remote_assignment("user", "u2", "Role1", "controller.inventory", object_id="2"),
            ],
            count=2,
        )
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([page1, page2], [team_resp])
        result = cmd._fetch_remote_assignment_set("controller")

        assert len(result.assignments) == 2
        assert not result.count_drifted

    def test_count_drift_detected(self):
        page1 = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Role1", "controller.inventory", object_id="1"),
            ],
            count=2,
            has_next=True,
        )
        page2 = _make_api_response(
            [
                _make_remote_assignment("user", "u2", "Role1", "controller.inventory", object_id="2"),
            ],
            count=3,
        )  # count changed from 2 to 3
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([page1, page2], [team_resp])
        result = cmd._fetch_remote_assignment_set("controller")

        assert result.count_drifted is True
        assert len(result.assignments) == 2

    def test_role_exclusion_filter_passed(self):
        user_resp = _make_api_response([], count=0)
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([user_resp], [team_resp])
        cmd._fetch_remote_assignment_set("hub")

        call_args = cmd.client.list_user_assignments.call_args
        filters = call_args[1]["filters"] if "filters" in call_args[1] else call_args[0][0]
        assert "not__role_definition__name__in" in filters

    def test_controller_no_exclusion_filter(self):
        user_resp = _make_api_response([], count=0)
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([user_resp], [team_resp])
        cmd._fetch_remote_assignment_set("controller")

        call_args = cmd.client.list_user_assignments.call_args
        filters = call_args[1]["filters"] if "filters" in call_args[1] else call_args[0][0]
        assert "not__role_definition__name__in" not in filters

    def test_page_size_uses_big_page_filters(self):
        user_resp = _make_api_response([], count=0)
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([user_resp], [team_resp])
        cmd._fetch_remote_assignment_set("controller")

        call_args = cmd.client.list_user_assignments.call_args
        filters = call_args[1]["filters"] if "filters" in call_args[1] else call_args[0][0]
        assert "page_size" in filters

    def test_http_error_stops_pagination(self):
        error_resp = Mock()
        error_resp.status_code = 500
        team_resp = _make_api_response([], count=0)

        cmd = self._make_cmd_with_client([error_resp], [team_resp])
        result = cmd._fetch_remote_assignment_set("controller")

        assert len(result.assignments) == 0

    def test_combines_user_and_team(self):
        user_resp = _make_api_response(
            [
                _make_remote_assignment("user", "u1", "Org Admin", "shared.organization", object_ansible_id="org1"),
            ],
            count=1,
        )
        team_resp = _make_api_response(
            [
                _make_remote_assignment("team", "t1", "Org Admin", "shared.organization", object_ansible_id="org1"),
            ],
            count=1,
        )

        cmd = self._make_cmd_with_client([user_resp], [team_resp])
        result = cmd._fetch_remote_assignment_set("controller")

        assert len(result.assignments) == 2
        types = {t.assignment_type for t in result.assignments}
        assert types == {"user", "team"}


# =============================================================================
# migrate_role_assignments (set-diff logic)
# =============================================================================


class TestMigrateRoleAssignments:
    def _make_cmd(self):
        cmd = MigrateCommand()
        cmd.client = Mock()
        cmd.stdout = Mock()
        cmd.stderr = Mock()
        return cmd

    @patch("aap_gateway_api.management.commands.migrate_service_data.get_local_assignments")
    def test_empty_diff_no_creates(self, mock_get_local):
        """When local and remote sets match, zero create calls should be made."""
        shared_set = {
            AssignmentTuple("u1", "org1", "Org Admin", "user"),
            AssignmentTuple("u2", None, "Platform Auditor", "user"),
        }
        mock_get_local.return_value = shared_set.copy()

        cmd = self._make_cmd()
        remote_result = _RemoteFetchResult(assignments=shared_set.copy(), count_drifted=False)

        with patch.object(cmd, "_fetch_remote_assignment_set", return_value=remote_result):
            with patch.object(cmd, "_create_assignment_from_tuple") as mock_create:
                cmd.migrate_role_assignments("controller", "controller")
                mock_create.assert_not_called()

    @patch("aap_gateway_api.management.commands.migrate_service_data.get_local_assignments")
    def test_creates_missing_assignments(self, mock_get_local):
        """Assignments in remote but not local should be created."""
        local_set = {AssignmentTuple("u1", "org1", "Org Admin", "user")}
        remote_set = {
            AssignmentTuple("u1", "org1", "Org Admin", "user"),
            AssignmentTuple("u2", "org1", "Org Member", "user"),
        }
        mock_get_local.return_value = local_set

        cmd = self._make_cmd()
        remote_result = _RemoteFetchResult(assignments=remote_set, count_drifted=False)

        with patch.object(cmd, "_fetch_remote_assignment_set", return_value=remote_result):
            with patch.object(cmd, "_create_assignment_from_tuple", return_value=True) as mock_create:
                cmd.migrate_role_assignments("controller", "controller")
                mock_create.assert_called_once()
                created_tuple = mock_create.call_args[0][0]
                assert created_tuple == AssignmentTuple("u2", "org1", "Org Member", "user")

    @patch("aap_gateway_api.management.commands.migrate_service_data.get_local_assignments")
    def test_count_drift_second_pass_converges(self, mock_get_local):
        """Count drift on first pass triggers second pass. If second pass is clean, no error."""
        local_set = {AssignmentTuple("u1", "org1", "Org Admin", "user")}
        remote_set = {
            AssignmentTuple("u1", "org1", "Org Admin", "user"),
            AssignmentTuple("u2", "org1", "Org Member", "user"),
        }
        mock_get_local.side_effect = [
            local_set,
            remote_set.copy(),  # second call returns updated local set
        ]

        cmd = self._make_cmd()
        first_result = _RemoteFetchResult(assignments=remote_set.copy(), count_drifted=True)
        second_result = _RemoteFetchResult(assignments=remote_set.copy(), count_drifted=False)

        with patch.object(cmd, "_fetch_remote_assignment_set", side_effect=[first_result, second_result]):
            with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
                cmd.migrate_role_assignments("controller", "controller")

    @patch("aap_gateway_api.management.commands.migrate_service_data.get_local_assignments")
    def test_count_drift_persistent_raises(self, mock_get_local):
        """Persistent count drift across both passes should raise RuntimeError."""
        local_set = set()
        remote_set = {AssignmentTuple("u1", "org1", "Org Admin", "user")}
        mock_get_local.return_value = local_set

        cmd = self._make_cmd()
        drifted_result = _RemoteFetchResult(assignments=remote_set.copy(), count_drifted=True)

        with patch.object(cmd, "_fetch_remote_assignment_set", return_value=drifted_result):
            with patch.object(cmd, "_create_assignment_from_tuple", return_value=True):
                with pytest.raises(RuntimeError, match="counts changed during both migration passes"):
                    cmd.migrate_role_assignments("controller", "controller")

    @patch("aap_gateway_api.management.commands.migrate_service_data.get_local_assignments")
    def test_does_not_delete_extra_local(self, mock_get_local):
        """Assignments in local but not remote should NOT be deleted."""
        local_set = {
            AssignmentTuple("u1", "org1", "Org Admin", "user"),
            AssignmentTuple("u2", "org2", "Org Admin", "user"),
        }
        remote_set = {AssignmentTuple("u1", "org1", "Org Admin", "user")}
        mock_get_local.return_value = local_set

        cmd = self._make_cmd()
        remote_result = _RemoteFetchResult(assignments=remote_set, count_drifted=False)

        with patch.object(cmd, "_fetch_remote_assignment_set", return_value=remote_result):
            with patch.object(cmd, "_create_assignment_from_tuple") as mock_create:
                cmd.migrate_role_assignments("controller", "controller")
                mock_create.assert_not_called()


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

    def test_missing_actor_resource_returns_false(self):
        cmd = MigrateCommand()
        cmd.stderr = Mock()
        RoleDefinition.objects.get_or_create(
            name="Test Role Create",
            defaults={"managed": False},
        )
        t = AssignmentTuple(str(uuid.uuid4()), None, "Test Role Create", "user")
        assert cmd._create_assignment_from_tuple(t) is False


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
