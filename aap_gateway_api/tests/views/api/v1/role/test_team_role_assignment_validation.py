# Tests for team role assignment validation - ensuring teams can only receive galaxy-only roles
import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition

from aap_gateway_api.models import Organization, Team


@pytest.fixture
def organization():
    """Create a test organization"""
    return Organization.objects.create(name='test-org')


@pytest.fixture
def team(organization):
    """Create a test team"""
    return Team.objects.create(name='test-team', organization=organization)


@pytest.fixture
def galaxy_content_type():
    """Create a content type for the galaxy service"""
    content_type, _ = DABContentType.objects.get_or_create(
        service='galaxy',
        app_label='galaxy_test',
        model='collection_test',
        defaults={'api_slug': 'galaxy.collection_test', 'pk_field_type': 'integer', 'pk': 9000},
    )
    return content_type


@pytest.fixture
def controller_content_type():
    """Create a content type for the controller service"""
    content_type, _ = DABContentType.objects.get_or_create(
        service='controller',
        app_label='controller_test',
        model='project_test',
        defaults={'api_slug': 'controller.project_test', 'pk_field_type': 'integer', 'pk': 9002},
    )
    return content_type


@pytest.fixture
def galaxy_permission(galaxy_content_type):
    """Create a permission for the galaxy service"""
    permission, _ = DABPermission.objects.get_or_create(
        content_type=galaxy_content_type,
        codename='view_collection_test',
        defaults={'name': 'Can view collection test', 'api_slug': 'galaxy.view_collection_test'},
    )
    return permission


@pytest.fixture
def controller_permission(controller_content_type):
    """Create a permission for the controller service"""
    permission, _ = DABPermission.objects.get_or_create(
        content_type=controller_content_type,
        codename='view_project_test',
        defaults={'name': 'Can view project test', 'api_slug': 'controller.view_project_test'},
    )
    return permission


@pytest.fixture
def galaxy_only_role(galaxy_permission):
    """Create a role with only galaxy permissions (should be assignable to teams)"""
    role = RoleDefinition.objects.create(
        name='Galaxy Only Role',
        description='A role with only galaxy permissions',
        content_type=None,  # System role
    )
    role.permissions.add(galaxy_permission)
    return role


@pytest.fixture
def platform_auditor_role():
    """Create a Platform Auditor-like role with non-galaxy permissions (should NOT be assignable to teams)"""
    return RoleDefinition.objects.get(name='Platform Auditor')


@pytest.fixture
def mixed_role(galaxy_permission, controller_permission):
    """Create a role with mixed galaxy and non-galaxy permissions (should NOT be assignable to teams)"""
    role = RoleDefinition.objects.create(
        name='Mixed Role',
        description='A role with both galaxy and non-galaxy permissions',
        content_type=None,  # System role
    )
    role.permissions.add(galaxy_permission, controller_permission)
    return role


@pytest.mark.django_db
class TestTeamRoleAssignmentValidation:
    """Tests for team role assignment validation - ensuring teams can only receive galaxy-only roles"""

    def test_team_cannot_be_assigned_platform_auditor_role(self, admin_api_client, team, organization, platform_auditor_role):
        """Test that Platform Auditor role (with controller permissions) cannot be assigned to a team"""
        data = {
            'team': team.id,
            'role_definition': platform_auditor_role.id,
            'object_id': organization.id,
        }

        response = admin_api_client.post(get_relative_url('roleteamassignment-list'), data, format='json')

        # Should return 400 because Platform Auditor has non-galaxy permissions
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert "Teams can only be assigned roles where all permissions are for the 'galaxy' service" in str(response.data)
        assert "Platform Auditor" in str(response.data)
        assert "view_team" in str(response.data)
        assert "service: shared" in str(response.data)

    def test_team_can_be_assigned_galaxy_only_role(self, admin_api_client, team, organization, galaxy_only_role):
        """Test that a role with only galaxy permissions can be assigned to a team"""
        data = {'team': team.id, 'role_definition': galaxy_only_role.id}

        response = admin_api_client.post(get_relative_url('roleteamassignment-list'), data, format='json')

        # Should succeed because the role only has galaxy permissions
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.data}"

    def test_team_cannot_be_assigned_mixed_role(self, admin_api_client, team, organization, mixed_role):
        """Test that a role with mixed galaxy and non-galaxy permissions cannot be assigned to a team"""
        data = {
            'team': team.id,
            'role_definition': mixed_role.id,
            'object_id': organization.id,
        }

        response = admin_api_client.post(get_relative_url('roleteamassignment-list'), data, format='json')

        # Should return 400 because the role has non-galaxy permissions
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert "Teams can only be assigned roles where all permissions are for the 'galaxy' service" in str(response.data)
        assert "Mixed Role" in str(response.data)
        assert "view_project_test" in str(response.data)
        assert "service: controller" in str(response.data)

    def test_team_assignment_with_galaxy_only_role_no_object(self, admin_api_client, team, galaxy_only_role):
        """Test that a galaxy-only role can be assigned to a team globally (without object_id)"""
        data = {
            'team': team.id,
            'role_definition': galaxy_only_role.id,
        }

        response = admin_api_client.post(get_relative_url('roleteamassignment-list'), data, format='json')

        # Should succeed because the role only has galaxy permissions
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.data}"

    def test_team_assignment_with_platform_auditor_no_object(self, admin_api_client, team, platform_auditor_role):
        """Test that Platform Auditor role cannot be assigned to a team globally (without object_id)"""
        data = {
            'team': team.id,
            'role_definition': platform_auditor_role.id,
        }

        response = admin_api_client.post(get_relative_url('roleteamassignment-list'), data, format='json')

        # Should return 400 because Platform Auditor has non-galaxy permissions
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert "Teams can only be assigned roles where all permissions are for the 'galaxy' service" in str(response.data)
