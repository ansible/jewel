from unittest.mock import Mock, patch

import pytest
from ansible_base.rbac.models import DABContentType, DABPermission
from django.contrib.auth import get_user_model

from aap_gateway_api.management.commands.migrate_service_data import Command

User = get_user_model()


@pytest.mark.django_db
class TestLoadTypesAndPermissions:
    """Test the load_types_and_permissions method"""

    @pytest.fixture
    def mock_user(self):
        """Create a mock user for testing"""
        return User.objects.create(username="testuser", is_superuser=True)

    @pytest.fixture
    def mock_service_api(self):
        """Create a mock service API route"""
        mock_service = Mock()
        mock_service.api_slug = "test-service"
        return mock_service

    @pytest.fixture
    def mock_service_apis(self, mock_service_api):
        """Create list of mock service APIs"""
        return [mock_service_api]

    @pytest.fixture
    def types_response_data(self):
        """Mock response data for role types"""
        return {
            "count": 19,
            "next": None,
            "previous": None,
            "results": [
                {
                    "api_slug": "shared.team",
                    "service": "shared",
                    "app_label": "test_app",
                    "model": "team",
                    "parent_content_type": "shared.organization",
                    "pk_field_type": "bigint",
                },
                {
                    "api_slug": "shared.organization",
                    "service": "shared",
                    "app_label": "test_app",
                    "model": "organization",
                    "parent_content_type": None,
                    "pk_field_type": "bigint",
                },
                {
                    "api_slug": "awx.inventory",
                    "service": "awx",
                    "app_label": "test_app",
                    "model": "inventory",
                    "parent_content_type": "shared.organization",
                    "pk_field_type": "bigint",
                },
            ],
        }

    @pytest.fixture
    def permissions_response_data(self):
        """Mock response data for role permissions"""
        return {
            "count": 82,
            "next": None,
            "previous": None,
            "results": [
                {"api_slug": "awx.add_inventory", "codename": "add_inventory", "content_type": "awx.inventory", "name": "Can add inventory"},
                {"api_slug": "awx.change_inventory", "codename": "change_inventory", "content_type": "awx.inventory", "name": "Can change inventory"},
                {"api_slug": "awx.delete_inventory", "codename": "delete_inventory", "content_type": "awx.inventory", "name": "Can delete inventory"},
                {"api_slug": "awx.view_inventory", "codename": "view_inventory", "content_type": "awx.inventory", "name": "Can view inventory"},
                {"api_slug": "awx.update_inventory", "codename": "update_inventory", "content_type": "awx.inventory", "name": "Do inventory updates"},
            ],
        }

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_and_permissions_success(self, mock_client_class, mock_user, mock_service_apis, types_response_data, permissions_response_data):
        """Test successful loading of types and permissions"""
        # Setup mock client instance
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup mock responses
        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_response_data

        mock_permissions_response = Mock()
        mock_permissions_response.status_code = 200
        mock_permissions_response.json.return_value = permissions_response_data

        # Configure client methods
        mock_client.list_role_types.return_value = mock_types_response
        mock_client.list_role_permissions.return_value = mock_permissions_response

        # Initialize command and call the method
        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)

        # Verify no services failed
        assert failed == []

        # Verify client was created with correct parameters
        mock_client_class.assert_called_once_with(mock_service_apis[0], raise_if_bad_request=True, user=mock_user)

        # Verify API calls were made with correct filters
        mock_client.list_role_types.assert_called_once_with(filters={"page_size": "200"})
        mock_client.list_role_permissions.assert_called_once_with(filters={"page_size": "200"})

        # Verify database objects were created
        # Check content types
        assert DABContentType.objects.filter(api_slug="shared.team").exists()
        assert DABContentType.objects.filter(api_slug="shared.organization").exists()
        assert DABContentType.objects.filter(api_slug="awx.inventory").exists()

        # Check permissions
        assert DABPermission.objects.filter(api_slug="awx.add_inventory").exists()
        assert DABPermission.objects.filter(api_slug="awx.change_inventory").exists()
        assert DABPermission.objects.filter(api_slug="awx.delete_inventory").exists()
        assert DABPermission.objects.filter(api_slug="awx.view_inventory").exists()
        assert DABPermission.objects.filter(api_slug="awx.update_inventory").exists()

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_and_permissions_multiple_services(self, mock_client_class, mock_user, types_response_data, permissions_response_data):
        """Test loading from multiple services"""
        # Create multiple mock services
        mock_service1 = Mock()
        mock_service1.api_slug = "service1"
        mock_service2 = Mock()
        mock_service2.api_slug = "service2"
        mock_service_apis = [mock_service1, mock_service2]

        # Setup mock client instance
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup mock responses
        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_response_data

        mock_permissions_response = Mock()
        mock_permissions_response.status_code = 200
        mock_permissions_response.json.return_value = permissions_response_data

        mock_client.list_role_types.return_value = mock_types_response
        mock_client.list_role_permissions.return_value = mock_permissions_response

        # Initialize command and call the method
        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)

        # Verify no services failed
        assert failed == []

        # Verify client was created for each service
        assert mock_client_class.call_count == 2
        mock_client_class.assert_any_call(mock_service1, raise_if_bad_request=True, user=mock_user)
        mock_client_class.assert_any_call(mock_service2, raise_if_bad_request=True, user=mock_user)

        # Verify API calls were made for each service
        assert mock_client.list_role_types.call_count == 2
        assert mock_client.list_role_permissions.call_count == 2

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_error_non_200_status(self, mock_client_class, mock_user, mock_service_apis):
        """Test that non-200 status for types is caught and the service is reported as failed"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup error response for types
        mock_types_response = Mock()
        mock_types_response.status_code = 500
        mock_types_response.data = "Internal Server Error"
        mock_client.list_role_types.return_value = mock_types_response

        command = Command()

        # Should not raise, but return the failed service slug
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)
        assert failed == ["test-service"]

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_permissions_error_non_200_status(self, mock_client_class, mock_user, mock_service_apis, types_response_data):
        """Test that non-200 status for permissions is caught and the service is reported as failed"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup successful types response
        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_response_data
        mock_client.list_role_types.return_value = mock_types_response

        # Setup error response for permissions
        mock_permissions_response = Mock()
        mock_permissions_response.status_code = 403
        mock_permissions_response.data = "Forbidden"
        mock_client.list_role_permissions.return_value = mock_permissions_response

        command = Command()

        # Should not raise, but return the failed service slug
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)
        assert failed == ["test-service"]

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_error_extra_pages(self, mock_client_class, mock_user, mock_service_apis):
        """Test that pagination in types response is caught and the service is reported as failed"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup response with pagination
        types_data_with_pagination = {"count": 250, "next": "/api/v1/service-index/role-types/?page=2", "previous": None, "results": []}

        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_data_with_pagination
        mock_client.list_role_types.return_value = mock_types_response

        command = Command()

        # Should not raise, but return the failed service slug
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)
        assert failed == ["test-service"]

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_permissions_error_extra_pages(self, mock_client_class, mock_user, mock_service_apis, types_response_data):
        """Test that pagination in permissions response is caught and the service is reported as failed"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Setup successful types response
        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_response_data
        mock_client.list_role_types.return_value = mock_types_response

        # Setup permissions response with pagination
        permissions_data_with_pagination = {"count": 300, "next": "/api/v1/service-index/role-permissions/?page=2", "previous": None, "results": []}

        mock_permissions_response = Mock()
        mock_permissions_response.status_code = 200
        mock_permissions_response.json.return_value = permissions_data_with_pagination
        mock_client.list_role_permissions.return_value = mock_permissions_response

        command = Command()

        # Should not raise, but return the failed service slug
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)
        assert failed == ["test-service"]

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_partial_failure_continues(self, mock_client_class, mock_user, types_response_data, permissions_response_data):
        """Test that when one service fails, the method continues to the next service and loads its data"""
        # Create two mock services: first will fail, second will succeed
        mock_service_failing = Mock()
        mock_service_failing.api_slug = "failing-service"
        mock_service_success = Mock()
        mock_service_success.api_slug = "success-service"
        mock_service_apis = [mock_service_failing, mock_service_success]

        # Setup failing client for first service
        mock_client_failing = Mock()
        mock_failing_types_response = Mock()
        mock_failing_types_response.status_code = 500
        mock_failing_types_response.data = "Internal Server Error"
        mock_client_failing.list_role_types.return_value = mock_failing_types_response

        # Setup successful client for second service
        mock_client_success = Mock()
        mock_success_types_response = Mock()
        mock_success_types_response.status_code = 200
        mock_success_types_response.json.return_value = types_response_data
        mock_client_success.list_role_types.return_value = mock_success_types_response

        mock_success_permissions_response = Mock()
        mock_success_permissions_response.status_code = 200
        mock_success_permissions_response.json.return_value = permissions_response_data
        mock_client_success.list_role_permissions.return_value = mock_success_permissions_response

        # Return different clients for different service APIs
        mock_client_class.side_effect = [mock_client_failing, mock_client_success]

        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)

        # Only the failing service should be in the failed list
        assert failed == ["failing-service"]

        # Content types from the successful service should be created
        assert DABContentType.objects.filter(api_slug="shared.team").exists()
        assert DABContentType.objects.filter(api_slug="shared.organization").exists()
        assert DABContentType.objects.filter(api_slug="awx.inventory").exists()

        # Permissions from the successful service should be created
        assert DABPermission.objects.filter(api_slug="awx.add_inventory").exists()
        assert DABPermission.objects.filter(api_slug="awx.view_inventory").exists()

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_connection_error_continues(self, mock_client_class, mock_user, types_response_data, permissions_response_data):
        """Test that a ConnectionError from one service does not prevent loading from subsequent services"""
        # Create two mock services: first raises ConnectionError, second succeeds
        mock_service_failing = Mock()
        mock_service_failing.api_slug = "unreachable-service"
        mock_service_success = Mock()
        mock_service_success.api_slug = "reachable-service"
        mock_service_apis = [mock_service_failing, mock_service_success]

        # First service raises ConnectionError when creating the client
        mock_client_success = Mock()
        mock_success_types_response = Mock()
        mock_success_types_response.status_code = 200
        mock_success_types_response.json.return_value = types_response_data
        mock_client_success.list_role_types.return_value = mock_success_types_response

        mock_success_permissions_response = Mock()
        mock_success_permissions_response.status_code = 200
        mock_success_permissions_response.json.return_value = permissions_response_data
        mock_client_success.list_role_permissions.return_value = mock_success_permissions_response

        # The first client creation raises ConnectionError, the second succeeds
        mock_client_class.side_effect = [ConnectionError("Connection refused"), mock_client_success]

        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)

        # The unreachable service should be in the failed list
        assert failed == ["unreachable-service"]

        # Content types from the reachable service should still be created
        assert DABContentType.objects.filter(api_slug="shared.team").exists()
        assert DABContentType.objects.filter(api_slug="awx.inventory").exists()

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_load_types_all_services_fail(self, mock_client_class, mock_user):
        """Test that when all services fail, the method returns all slugs without raising"""
        mock_service1 = Mock()
        mock_service1.api_slug = "service1"
        mock_service2 = Mock()
        mock_service2.api_slug = "service2"
        mock_service_apis = [mock_service1, mock_service2]

        # Both clients fail
        mock_client_class.side_effect = [ConnectionError("Connection refused"), ConnectionError("Connection refused")]

        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)

        assert failed == ["service1", "service2"]

    @patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient')
    def test_database_objects_creation_details(self, mock_client_class, mock_user, mock_service_apis, types_response_data, permissions_response_data):
        """Test detailed verification of database objects creation"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_types_response = Mock()
        mock_types_response.status_code = 200
        mock_types_response.json.return_value = types_response_data

        mock_permissions_response = Mock()
        mock_permissions_response.status_code = 200
        mock_permissions_response.json.return_value = permissions_response_data

        mock_client.list_role_types.return_value = mock_types_response
        mock_client.list_role_permissions.return_value = mock_permissions_response

        command = Command()
        failed = command.load_types_and_permissions(mock_service_apis, mock_user)
        assert failed == []

        shared_team = DABContentType.objects.get(api_slug="shared.team")
        assert shared_team.service == "shared"
        # Important, the command should not change the app_label of shared resources
        # it is expected that shared models will have different app_label values
        # in different components, but they should not be updated where entry exists locally
        assert shared_team.app_label == "aap_gateway_api"
        assert shared_team.model == "team"
        assert shared_team.parent_content_type.api_slug == "shared.organization"
        assert shared_team.pk_field_type == "bigint"

        # Verify permissions with detailed attributes
        add_inventory = DABPermission.objects.get(api_slug="awx.add_inventory")
        assert add_inventory.codename == "add_inventory"
        assert add_inventory.content_type.api_slug == "awx.inventory"
        assert add_inventory.name == "Can add inventory"

        update_inventory = DABPermission.objects.get(api_slug="awx.update_inventory")
        assert update_inventory.codename == "update_inventory"
        assert update_inventory.content_type.api_slug == "awx.inventory"
        assert update_inventory.name == "Do inventory updates"
