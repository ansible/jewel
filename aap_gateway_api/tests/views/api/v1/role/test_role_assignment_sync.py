from unittest.mock import Mock, patch

import pytest
import requests
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.remote import RemoteObject
from rest_framework.test import APIClient

from aap_gateway_api.models import HTTPPort, Organization, ServiceAPIRoute, ServiceCluster, ServiceType, Team, User


@pytest.mark.django_db
class TestAssignmentSyncMixin:
    """Tests for AssignmentSyncMixin focusing on resource client mocking"""

    @pytest.fixture
    def api_client(self):
        return APIClient()

    @pytest.fixture
    def superuser(self):
        user = User.objects.create(username='admin', is_superuser=True)
        user.set_password('password')
        user.save()
        return user

    @pytest.fixture
    def regular_user(self):
        return User.objects.create(username='testuser')

    @pytest.fixture
    def team(self, organization):
        return Team.objects.create(name='testteam', organization=organization)

    @pytest.fixture
    def organization(self):
        return Organization.objects.create(name='testorg')

    @pytest.fixture
    def gateway_role_definition(self):
        """Role definition for gateway-owned resources (shared service)"""
        return RoleDefinition.objects.create(
            name='Gateway Role', content_type=DABContentType.objects.get_for_model(Organization), description='A gateway-owned role'
        )

    @pytest.fixture
    def service_role_definition(self):
        """Role definition for service-specific resources (awx inventory)"""
        # Use get_or_create with unique app_label/model combination
        ct, created = DABContentType.objects.get_or_create(
            service='awx',
            model='inventory',
            defaults={
                'id': max(DABContentType.objects.values_list('id', flat=True)) + 1,
                'app_label': 'awx',
                'api_slug': 'awx.inventory',
                'pk_field_type': 'integer',
            },
        )
        if not created:
            ct.service = 'awx'  # External AWX service
            ct.save()

        # Use get_or_create for role definition too
        role_def, created = RoleDefinition.objects.get_or_create(
            name='AWX Inventory Role', content_type=ct, defaults={'description': 'An AWX inventory-specific role'}
        )
        return role_def

    @pytest.fixture
    def mock_inventory(self, service_role_definition):
        """Mock inventory object using RemoteObject for service-specific tests"""
        return RemoteObject(object_id=123, content_type=service_role_definition.content_type)

    @pytest.fixture
    def http_port(self):
        """Mock HTTP port needed by ServiceAPIRoute"""
        http_port, created = HTTPPort.objects.get_or_create(name='api-port', defaults={'number': 8000, 'is_api_port': True, 'use_https': False})
        return http_port

    @pytest.fixture
    def service_api_route(self, http_port):
        """Mock service API route for service-specific roles"""
        service_type, created = ServiceType.objects.get_or_create(name='awx', defaults={'service_index_path': '/api/v2/'})
        service_cluster, created = ServiceCluster.objects.get_or_create(name='test-cluster', defaults={'service_type': service_type})
        service_api_route, created = ServiceAPIRoute.objects.get_or_create(
            api_slug='awx',
            defaults={
                'name': 'awx-service',
                'service_cluster': service_cluster,
                'gateway_path': '/awx/',
                'http_port': http_port,
                'service_port': 8000,
                'is_service_https': False,
            },
        )
        return service_api_route

    @pytest.fixture
    def authenticated_client(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        return api_client


@pytest.mark.django_db
class TestGatewayRoleUserAssignmentViewSet(TestAssignmentSyncMixin):
    """Tests for GatewayRoleUserAssignmentViewSet"""

    def get_assignment_url(self):
        return get_relative_url('roleuserassignment-list')

    def get_assignment_detail_url(self, assignment_id):
        return get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment_id})

    @patch('aap_gateway_api.views.api.v1.common.AllServicesClient')
    def test_create_assignment_gateway_owned_role(self, mock_client_class, authenticated_client, regular_user, organization, gateway_role_definition):
        """Test creating role assignment for gateway-owned role definition"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        data = {'user': regular_user.id, 'object_id': organization.id, 'role_definition': gateway_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        assert response.status_code == 201

        # Verify assignment was created
        assignment = RoleUserAssignment.objects.get(user=regular_user, object_id=organization.id, role_definition=gateway_role_definition)
        assert assignment is not None

        # Verify AllServicesClient was used for gateway-owned role
        mock_client_class.assert_called_once()
        mock_client.sync_assignment.assert_called_once_with(assignment)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_create_assignment_service_specific_role(
        self, mock_service_get, mock_direct_client_class, authenticated_client, regular_user, mock_inventory, service_role_definition, service_api_route
    ):
        """Test creating role assignment for service-specific role definition"""
        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        data = {'user': regular_user.id, 'object_id': mock_inventory.object_id, 'role_definition': service_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        assert response.status_code == 201

        # Verify assignment was created
        assignment = RoleUserAssignment.objects.get(user=regular_user, object_id=mock_inventory.object_id, role_definition=service_role_definition)
        assert assignment is not None

        # Verify direct client was used for service-specific role
        mock_direct_client_class.assert_called_once_with(service_api_route, raise_if_bad_request=True)
        mock_direct_client.sync_assignment.assert_called_once_with(assignment)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_create_assignment_service_http_error(
        self, mock_service_get, mock_direct_client_class, authenticated_client, regular_user, organization, service_role_definition, service_api_route
    ):
        """Test HTTP error handling when creating service-specific assignment"""
        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {'error': 'Bad request from service'}

        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_direct_client.sync_assignment.side_effect = http_error

        data = {'user': regular_user.id, 'object_id': organization.id, 'role_definition': service_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        # Should return 400 with the proxied error
        assert response.status_code == 400
        assert response.data == {'error': 'Bad request from service'}

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_create_assignment_service_http_error_no_json(
        self, mock_service_get, mock_direct_client_class, authenticated_client, regular_user, organization, service_role_definition, service_api_route
    ):
        """Test HTTP error handling when service returns non-JSON error"""
        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        # Mock HTTP error response with non-JSON content
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.side_effect = Exception("Not JSON")
        mock_response.text = "Internal Server Error"

        http_error = requests.HTTPError()
        http_error.response = mock_response
        mock_direct_client.sync_assignment.side_effect = http_error

        data = {'user': regular_user.id, 'object_id': organization.id, 'role_definition': service_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        # Should return 500 with the text error
        assert response.status_code == 500
        assert response.data == {'detail': 'Internal Server Error'}

    @patch('aap_gateway_api.views.api.v1.common.AllServicesClient')
    def test_delete_assignment_gateway_owned_role(self, mock_client_class, authenticated_client, regular_user, organization, gateway_role_definition):
        """Test deleting role assignment for gateway-owned role definition"""
        # Create assignment first
        assignment = gateway_role_definition.give_permission(regular_user, organization)

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        response = authenticated_client.delete(self.get_assignment_detail_url(assignment.id))

        assert response.status_code == 204

        # Verify assignment was deleted
        assert not RoleUserAssignment.objects.filter(id=assignment.id).exists()

        # Verify AllServicesClient was used for unassignment
        mock_client_class.assert_called_once()
        mock_client.sync_unassignment.assert_called_once_with(gateway_role_definition, regular_user, organization)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_delete_assignment_service_specific_role(
        self, mock_service_get, mock_direct_client_class, authenticated_client, regular_user, mock_inventory, service_role_definition, service_api_route
    ):
        """Test deleting role assignment for service-specific role definition"""
        # Create assignment first - use direct DB creation to avoid validation
        assignment = service_role_definition.give_permission(regular_user, mock_inventory)

        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        response = authenticated_client.delete(self.get_assignment_detail_url(assignment.id))

        assert response.status_code == 204

        # Verify assignment was deleted
        assert not RoleUserAssignment.objects.filter(id=assignment.id).exists()

        # Verify direct client was used for unassignment
        mock_direct_client_class.assert_called_with(service_api_route, raise_if_bad_request=True)
        mock_direct_client.sync_unassignment.assert_called_with(service_role_definition, regular_user, mock_inventory)


@pytest.mark.django_db
class TestGatewayRoleTeamAssignmentViewSet(TestAssignmentSyncMixin):
    """Tests for GatewayRoleTeamAssignmentViewSet"""

    def get_assignment_url(self):
        return get_relative_url('roleteamassignment-list')

    def get_assignment_detail_url(self, assignment_id):
        return get_relative_url('roleteamassignment-detail', kwargs={'pk': assignment_id})

    @patch('aap_gateway_api.views.api.v1.common.AllServicesClient')
    def test_create_team_assignment_gateway_owned_role(self, mock_client_class, authenticated_client, team, organization, gateway_role_definition):
        """Test creating team role assignment for gateway-owned role definition"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        data = {'team': team.id, 'object_id': organization.id, 'role_definition': gateway_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        assert response.status_code == 201

        # Verify assignment was created
        assignment = RoleTeamAssignment.objects.get(team=team, object_id=organization.id, role_definition=gateway_role_definition)
        assert assignment is not None

        # Verify AllServicesClient was used for gateway-owned role
        mock_client_class.assert_called_once()
        mock_client.sync_assignment.assert_called_once_with(assignment)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_create_team_assignment_service_specific_role(
        self, mock_service_get, mock_direct_client_class, authenticated_client, team, mock_inventory, service_role_definition, service_api_route
    ):
        """Test creating team role assignment for service-specific role definition"""
        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        data = {'team': team.id, 'object_id': mock_inventory.object_id, 'role_definition': service_role_definition.id}

        response = authenticated_client.post(self.get_assignment_url(), data)

        assert response.status_code == 201

        # Verify assignment was created
        assignment = RoleTeamAssignment.objects.get(team=team, object_id=mock_inventory.object_id, role_definition=service_role_definition)
        assert assignment is not None

        # Verify direct client was used for service-specific role
        mock_direct_client_class.assert_called_once_with(service_api_route, raise_if_bad_request=True)
        mock_direct_client.sync_assignment.assert_called_once_with(assignment)

    @patch('aap_gateway_api.views.api.v1.common.AllServicesClient')
    def test_delete_team_assignment_gateway_owned_role(self, mock_client_class, authenticated_client, team, organization, gateway_role_definition):
        """Test deleting team role assignment for gateway-owned role definition"""
        # Create assignment first
        assignment = gateway_role_definition.give_permission(team, organization)

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        response = authenticated_client.delete(self.get_assignment_detail_url(assignment.id))

        assert response.status_code == 204

        # Verify assignment was deleted
        assert not RoleTeamAssignment.objects.filter(id=assignment.id).exists()

        # Verify AllServicesClient was used for unassignment
        mock_client_class.assert_called_once()
        mock_client.sync_unassignment.assert_called_once_with(gateway_role_definition, team, organization)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_delete_team_assignment_service_specific_role(
        self, mock_service_get, mock_direct_client_class, authenticated_client, team, mock_inventory, service_role_definition, service_api_route
    ):
        """Test deleting team role assignment for service-specific role definition"""
        # Create assignment first
        assignment = service_role_definition.give_permission(team, mock_inventory)

        mock_service_get.return_value = service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        response = authenticated_client.delete(self.get_assignment_detail_url(assignment.id))

        assert response.status_code == 204

        # Verify assignment was deleted
        assert not RoleTeamAssignment.objects.filter(id=assignment.id).exists()

        # Verify direct client was used for unassignment
        mock_direct_client_class.assert_called_with(service_api_route, raise_if_bad_request=True)
        mock_direct_client.sync_unassignment.assert_called_with(service_role_definition, team, mock_inventory)


@pytest.mark.django_db
class TestAssignmentSyncMixinMethods:
    """Tests for specific methods in AssignmentSyncMixin"""

    def get_assignment_url(self):
        return get_relative_url('roleuserassignment-list')

    @pytest.fixture
    def regular_user(self):
        return User.objects.create(username='testuser')

    @pytest.fixture
    def http_port(self):
        """Mock HTTP port needed by ServiceAPIRoute"""
        http_port, _ = HTTPPort.objects.get_or_create(name='api-port', defaults={'number': 8000, 'is_api_port': True, 'use_https': False})
        return http_port

    @pytest.fixture
    def viewset_instance(self):
        """Create a mock viewset instance to test mixin methods"""
        from aap_gateway_api.views.api.v1.role import GatewayRoleUserAssignmentViewSet

        viewset = GatewayRoleUserAssignmentViewSet()
        viewset.request = Mock()
        viewset.request.user = Mock()
        return viewset

    def test_is_owned_by_gateway_none_role_definition(self, viewset_instance):
        """Test _is_owned_by_gateway returns True for None role definition"""
        result = viewset_instance._is_owned_by_gateway(None)
        assert result is True

    def test_is_owned_by_gateway_aap_service(self, viewset_instance):
        """Test _is_owned_by_gateway returns True for 'aap' service"""
        mock_role_def = Mock()
        mock_role_def.content_type.service = 'aap'

        result = viewset_instance._is_owned_by_gateway(mock_role_def)
        assert result is True

    def test_is_owned_by_gateway_shared_service(self, viewset_instance):
        """Test _is_owned_by_gateway returns True for 'shared' service"""
        mock_role_def = Mock()
        mock_role_def.content_type.service = 'shared'

        result = viewset_instance._is_owned_by_gateway(mock_role_def)
        assert result is True

    def test_is_owned_by_gateway_external_service(self, viewset_instance):
        """Test _is_owned_by_gateway returns False for external service"""
        mock_role_def = Mock()
        mock_role_def.content_type.service = 'awx'

        result = viewset_instance._is_owned_by_gateway(mock_role_def)
        assert result is False

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    @patch('aap_gateway_api.views.api.v1.role.service_type_to_api_slug')
    def test_get_direct_client(self, mock_slug_func, mock_service_get, mock_client_class, viewset_instance):
        """Test get_direct_client creates correct client for service-specific role"""
        mock_slug_func.return_value = 'awx'
        mock_service = Mock()
        mock_service_get.return_value = mock_service

        mock_role_def = Mock()
        mock_role_def.content_type.service = 'awx'

        result = viewset_instance.get_direct_client(mock_role_def)

        mock_slug_func.assert_called_once_with('awx')
        mock_service_get.assert_called_once_with(api_slug='awx')
        mock_client_class.assert_called_once_with(mock_service, raise_if_bad_request=True)

        assert result == mock_client_class.return_value

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_get_direct_client_galaxy_service_maps_correctly(self, mock_service_get, mock_client_class, viewset_instance):
        """Test get_direct_client correctly maps galaxy service to galaxy api_slug after fix for AAP-51363"""
        mock_service = Mock()
        mock_service_get.return_value = mock_service

        mock_role_def = Mock()
        mock_role_def.content_type.service = 'galaxy'

        result = viewset_instance.get_direct_client(mock_role_def)

        # After fix, galaxy service should map to galaxy api_slug, not hub
        mock_service_get.assert_called_once_with(api_slug='galaxy')
        mock_client_class.assert_called_once_with(mock_service, raise_if_bad_request=True)

        assert result == mock_client_class.return_value

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_get_direct_client_awx_service_maps_to_controller(self, mock_service_get, mock_client_class, viewset_instance):
        """Test get_direct_client correctly maps awx service to controller api_slug"""
        mock_service = Mock()
        mock_service_get.return_value = mock_service

        mock_role_def = Mock()
        mock_role_def.content_type.service = 'awx'

        result = viewset_instance.get_direct_client(mock_role_def)

        # AWX service should still map to controller api_slug
        mock_service_get.assert_called_once_with(api_slug='controller')
        mock_client_class.assert_called_once_with(mock_service, raise_if_bad_request=True)

        assert result == mock_client_class.return_value

    @pytest.fixture
    def galaxy_role_definition(self):
        """Role definition for galaxy service resources (hub collection)"""
        # Create content type for galaxy service
        ct, created = DABContentType.objects.get_or_create(
            service='galaxy',
            model='collection',
            defaults={
                'id': max(DABContentType.objects.values_list('id', flat=True)) + 1,
                'app_label': 'galaxy',
                'api_slug': 'galaxy.collection',
                'pk_field_type': 'integer',
            },
        )
        if not created:
            ct.service = 'galaxy'  # Ensure service is galaxy
            ct.save()

        # Create role definition for galaxy resources
        role_def, created = RoleDefinition.objects.get_or_create(
            name='Galaxy Collection Role', content_type=ct, defaults={'description': 'A galaxy collection-specific role'}
        )
        return role_def

    @pytest.fixture
    def galaxy_service_api_route(self, http_port):
        """Mock service API route for galaxy service"""
        service_type, created = ServiceType.objects.get_or_create(name='galaxy', defaults={'service_index_path': '/pulp/api/v3/'})
        service_cluster, created = ServiceCluster.objects.get_or_create(name='galaxy-cluster', defaults={'service_type': service_type})
        service_api_route, created = ServiceAPIRoute.objects.get_or_create(
            api_slug='galaxy',
            defaults={
                'name': 'galaxy-service',
                'service_cluster': service_cluster,
                'gateway_path': '/galaxy/',
                'http_port': http_port,
                'service_port': 8080,
                'is_service_https': False,
            },
        )
        return service_api_route

    @pytest.fixture
    def mock_galaxy_collection(self, galaxy_role_definition):
        """Mock galaxy collection object using RemoteObject for service-specific tests"""
        return RemoteObject(object_id=456, content_type=galaxy_role_definition.content_type)

    @patch('aap_gateway_api.views.api.v1.role.GWResourceAPIClient')
    @patch('aap_gateway_api.models.ServiceAPIRoute.objects.get')
    def test_create_assignment_galaxy_service_role_aap_51363_fix(
        self,
        mock_service_get,
        mock_direct_client_class,
        admin_api_client,
        regular_user,
        mock_galaxy_collection,
        galaxy_role_definition,
        galaxy_service_api_route,
    ):
        """Test creating role assignment for galaxy service role (AAP-51363 fix)

        This test reproduces the original bug scenario where:
        1. Role definition has content_type.service = 'galaxy'
        2. service_type_to_api_slug('galaxy') should return 'galaxy' (not 'hub')
        3. ServiceAPIRoute.objects.get(api_slug='galaxy') should succeed
        """
        mock_service_get.return_value = galaxy_service_api_route
        mock_direct_client = Mock()
        mock_direct_client_class.return_value = mock_direct_client

        data = {'user': regular_user.id, 'object_id': mock_galaxy_collection.object_id, 'role_definition': galaxy_role_definition.id}

        response = admin_api_client.post(self.get_assignment_url(), data)

        assert response.status_code == 201

        # Verify assignment was created
        assignment = RoleUserAssignment.objects.get(user=regular_user, object_id=mock_galaxy_collection.object_id, role_definition=galaxy_role_definition)
        assert assignment is not None

        # Verify ServiceAPIRoute lookup used 'galaxy' api_slug (not 'hub')
        mock_service_get.assert_called_once_with(api_slug='galaxy')

        # Verify direct client was used for service-specific role
        mock_direct_client_class.assert_called_once_with(galaxy_service_api_route, raise_if_bad_request=True)
        mock_direct_client.sync_assignment.assert_called_once_with(assignment)
