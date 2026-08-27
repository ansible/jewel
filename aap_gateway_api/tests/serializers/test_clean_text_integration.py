"""Integration tests verifying CleanTextMixin is correctly wired to Gateway serializers.

These tests verify that the CleanTextMixin validation (two-tier text validation with
grandfathering) works correctly on all Gateway serializers that were updated in AAP-78708.

The validation is gated behind ENHANCED_INPUT_VALIDATION_ENABLED, so all test classes
use @override_settings to enable it.
"""

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from django.test import override_settings

from aap_gateway_api.models import AdditionalRoute, CACertificate, HTTPPort, Organization, ServiceCluster, ServiceNode, ServiceType, Team
from aap_gateway_api.serializers import (
    AdditionalRouteSerializer,
    CACertificateSerializer,
    HTTPPortSerializer,
    ServiceClusterSerializer,
    ServiceKeySerializer,
    ServiceNodeSerializer,
    ServiceTypeSerializer,
)

DANGEROUS_NAME = '<script>alert(1)</script>'
DANGEROUS_TEXT = '$(rm -rf /)'
VALID_NAME = 'Valid Resource Name'


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestOrganizationCleanText:
    """Test CleanTextMixin integration with OrganizationSerializer."""

    def test_rejects_invalid_name_on_create(self, admin_api_client):
        """POST with dangerous name characters should return HTTP 400."""
        url = get_relative_url('organization-list')
        data = {'name': DANGEROUS_NAME}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_accepts_valid_name_on_create(self, admin_api_client):
        """POST with valid name should succeed."""
        url = get_relative_url('organization-list')
        data = {'name': VALID_NAME}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201
        assert response.data['name'] == VALID_NAME

    def test_rejects_invalid_description_on_create(self, admin_api_client):
        """POST with dangerous description should return HTTP 400."""
        url = get_relative_url('organization-list')
        data = {'name': VALID_NAME, 'description': DANGEROUS_TEXT}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_grandfather_unchanged_name_on_update(self, admin_api_client):
        """PATCH that doesn't change invalid name should succeed (grandfathering)."""
        # Create with valid name
        url = get_relative_url('organization-list')
        response = admin_api_client.post(url, data={'name': 'Temp Org'}, format='json')
        assert response.status_code == 201
        org_id = response.data['id']

        # Manually update DB to invalid name (simulating pre-validation data)
        Organization.objects.filter(pk=org_id).update(name='name;semicolon')

        # PATCH without changing the name - should succeed
        detail_url = get_relative_url('organization-detail', kwargs={'pk': org_id})
        response = admin_api_client.patch(detail_url, data={'name': 'name;semicolon', 'description': 'Updated description'}, format='json')
        assert response.status_code == 200

    def test_rejects_changed_invalid_name_on_update(self, admin_api_client, organization):
        """PATCH that changes name to invalid value should return HTTP 400."""
        detail_url = get_relative_url('organization-detail', kwargs={'pk': organization.pk})
        response = admin_api_client.patch(detail_url, data={'name': DANGEROUS_NAME}, format='json')
        assert response.status_code == 400
        assert 'name' in response.data


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestTeamCleanText:
    """Test CleanTextMixin integration with TeamSerializer."""

    def test_rejects_invalid_name_on_create(self, admin_api_client, organization):
        """POST with dangerous name should return HTTP 400."""
        url = get_relative_url('team-list')
        data = {'name': DANGEROUS_NAME, 'organization': organization.id}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_accepts_valid_name_on_create(self, admin_api_client, organization):
        """POST with valid name should succeed."""
        url = get_relative_url('team-list')
        data = {'name': VALID_NAME, 'organization': organization.id}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_rejects_invalid_description_on_create(self, admin_api_client, organization):
        """POST with dangerous description should return HTTP 400."""
        url = get_relative_url('team-list')
        data = {'name': VALID_NAME, 'organization': organization.id, 'description': DANGEROUS_TEXT}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_grandfather_unchanged_name_on_update(self, admin_api_client, organization):
        """PATCH that doesn't change invalid name should succeed."""
        url = get_relative_url('team-list')
        response = admin_api_client.post(url, data={'name': 'Temp Team', 'organization': organization.id}, format='json')
        assert response.status_code == 201
        team_id = response.data['id']

        # Manually update to invalid name
        Team.objects.filter(pk=team_id).update(name='team<invalid>')

        # PATCH without changing name - should succeed
        detail_url = get_relative_url('team-detail', kwargs={'pk': team_id})
        response = admin_api_client.patch(detail_url, data={'name': 'team<invalid>', 'description': 'Updated'}, format='json')
        assert response.status_code == 200


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestUserCleanText:
    """Test CleanTextMixin integration with UserSerializer."""

    def test_rejects_invalid_username_on_create(self, admin_api_client):
        """POST with dangerous username should return HTTP 400."""
        url = get_relative_url('user-list')
        data = {'username': DANGEROUS_NAME}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'username' in response.data

    def test_accepts_valid_username_on_create(self, admin_api_client):
        """POST with valid username should succeed."""
        url = get_relative_url('user-list')
        data = {'username': 'valid_user_123'}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_rejects_invalid_first_name_on_create(self, admin_api_client):
        """POST with dangerous first_name should return HTTP 400 (Tier 2 validation)."""
        url = get_relative_url('user-list')
        data = {'username': 'testuser', 'first_name': DANGEROUS_TEXT}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'first_name' in response.data

    def test_rejects_invalid_last_name_on_create(self, admin_api_client):
        """POST with dangerous last_name should return HTTP 400 (Tier 2 validation)."""
        url = get_relative_url('user-list')
        data = {'username': 'testuser', 'last_name': DANGEROUS_TEXT}
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'last_name' in response.data


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestGatewayRoleDefinitionCleanText:
    """Test CleanTextMixin integration with GatewayRoleDefinitionSerializer."""

    def test_rejects_invalid_name_on_create(self, admin_api_client):
        """POST with dangerous name should return HTTP 400."""
        url = get_relative_url('roledefinition-list')
        data = {
            'name': DANGEROUS_NAME,
            'description': 'Valid description',
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'name' in response.data

    def test_rejects_invalid_description_on_create(self, admin_api_client):
        """POST with dangerous description should return HTTP 400."""
        url = get_relative_url('roledefinition-list')
        data = {
            'name': VALID_NAME,
            'description': DANGEROUS_TEXT,
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400
        assert 'description' in response.data

    def test_accepts_valid_data_on_create(self, admin_api_client):
        """POST with valid data should succeed."""
        url = get_relative_url('roledefinition-list')
        data = {
            'name': VALID_NAME,
            'description': 'A role for viewing organizations',
            'permissions': ['shared.view_organization'],
            'content_type': 'shared.organization',
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 201

    def test_grandfather_unchanged_name_on_update(self, admin_api_client):
        """PATCH that doesn't change invalid name should succeed."""
        url = get_relative_url('roledefinition-list')
        response = admin_api_client.post(
            url,
            data={
                'name': 'Temp Role',
                'description': 'Original',
                'permissions': ['shared.view_organization'],
                'content_type': 'shared.organization',
            },
            format='json',
        )
        assert response.status_code == 201
        rd_id = response.data['id']

        # Manually update to invalid name
        RoleDefinition.objects.filter(pk=rd_id).update(name='role$invalid')

        # PATCH without changing name - should succeed
        detail_url = get_relative_url('roledefinition-detail', kwargs={'pk': rd_id})
        response = admin_api_client.patch(detail_url, data={'name': 'role$invalid', 'description': 'Updated'}, format='json')
        assert response.status_code == 200


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestServiceClusterCleanText:
    """Test CleanTextMixin integration with ServiceClusterSerializer."""

    def test_rejects_invalid_name_at_serializer_level(self):
        """Serializer-level validation should reject invalid name."""
        serializer = ServiceClusterSerializer(data={'name': DANGEROUS_NAME})
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_accepts_valid_name_at_serializer_level(self):
        """Serializer-level validation should accept valid name."""
        serializer = ServiceClusterSerializer(
            data={
                'name': VALID_NAME,
                'service_type': 'gateway',
            }
        )
        # May have other validation errors, but name should not be one
        serializer.is_valid()
        assert 'name' not in serializer.errors

    def test_grandfather_unchanged_name_on_update(self):
        """Update that doesn't change invalid name should succeed."""
        # Create with valid name
        cluster = ServiceCluster.objects.create(name='valid-cluster', service_type='gateway')

        # Manually update to invalid name
        ServiceCluster.objects.filter(pk=cluster.pk).update(name='cluster;invalid')
        cluster.refresh_from_db()

        # Serialize update without changing name - should succeed
        serializer = ServiceClusterSerializer(instance=cluster, data={'name': 'cluster;invalid', 'service_type': 'gateway'}, partial=True)
        assert serializer.is_valid()


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestRouteSerializersCleanText:
    """Test CleanTextMixin integration with route serializers (via BaseRouteSerializer)."""

    def test_additional_route_rejects_invalid_name(self, http_port, service_cluster_gateway):
        """AdditionalRouteSerializer should reject invalid name."""
        serializer = AdditionalRouteSerializer(
            data={
                'name': DANGEROUS_NAME,
                'http_port': http_port.id,
                'service_cluster': service_cluster_gateway.id,
                'gateway_path': '/test/',
            }
        )
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_additional_route_rejects_invalid_description(self, http_port, service_cluster_gateway):
        """AdditionalRouteSerializer should reject dangerous description."""
        serializer = AdditionalRouteSerializer(
            data={
                'name': VALID_NAME,
                'description': DANGEROUS_TEXT,
                'http_port': http_port.id,
                'service_cluster': service_cluster_gateway.id,
                'gateway_path': '/test/',
            }
        )
        assert not serializer.is_valid()
        assert 'description' in serializer.errors

    def test_additional_route_grandfather_unchanged_name(self, http_port, service_cluster_gateway):
        """Update without changing invalid name should succeed."""
        route = AdditionalRoute.objects.create(
            name='valid-route',
            http_port=http_port,
            service_cluster=service_cluster_gateway,
            gateway_path='/test/',
        )

        # Manually update to invalid
        AdditionalRoute.objects.filter(pk=route.pk).update(name='route<invalid>')
        route.refresh_from_db()

        serializer = AdditionalRouteSerializer(instance=route, data={'name': 'route<invalid>'}, partial=True)
        assert serializer.is_valid()


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestServiceNodeCleanText:
    """Test CleanTextMixin integration with ServiceNodeSerializer."""

    def test_rejects_invalid_name_at_serializer_level(self, service_cluster_gateway):
        """Serializer should reject invalid name."""
        serializer = ServiceNodeSerializer(
            data={
                'name': DANGEROUS_NAME,
                'address': '192.168.1.1',
                'service_cluster': service_cluster_gateway.id,
            }
        )
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_accepts_valid_name(self, service_cluster_gateway):
        """Serializer should accept valid name."""
        serializer = ServiceNodeSerializer(
            data={
                'name': VALID_NAME,
                'address': '192.168.1.1',
                'service_cluster': service_cluster_gateway.id,
            }
        )
        assert serializer.is_valid()

    def test_grandfather_unchanged_name_on_update(self, service_cluster_gateway):
        """Update without changing invalid name should succeed."""
        node = ServiceNode.objects.create(
            name='valid-node',
            address='192.168.1.1',
            service_cluster=service_cluster_gateway,
        )

        ServiceNode.objects.filter(pk=node.pk).update(name='node`invalid')
        node.refresh_from_db()

        serializer = ServiceNodeSerializer(instance=node, data={'name': 'node`invalid'}, partial=True)
        assert serializer.is_valid()


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestServiceKeyCleanText:
    """Test CleanTextMixin integration with ServiceKeySerializer.

    Note: ServiceKeySerializer has custom create() logic, so we test
    validation at the serializer level rather than via API endpoints.
    """

    def test_rejects_invalid_name_at_serializer_level(self, service_cluster_gateway):
        """Serializer should reject invalid name."""
        serializer = ServiceKeySerializer(
            data={
                'name': DANGEROUS_NAME,
                'service_cluster': service_cluster_gateway.id,
                'mark_previous_inactive': False,
            }
        )
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_accepts_valid_name(self, service_cluster_gateway):
        """Serializer should accept valid name."""
        serializer = ServiceKeySerializer(
            data={
                'name': VALID_NAME,
                'service_cluster': service_cluster_gateway.id,
                'mark_previous_inactive': False,
            }
        )
        # May have other validation, but name should not error
        serializer.is_valid()
        assert 'name' not in serializer.errors


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestCACertificateCleanText:
    """Test CleanTextMixin integration with CACertificateSerializer."""

    def test_rejects_invalid_name_at_serializer_level(self):
        """Serializer-level validation should reject invalid name."""
        serializer = CACertificateSerializer(data={'name': DANGEROUS_NAME, 'pem_data': 'not-a-cert', 'sha256': 'abc123'})
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_accepts_valid_name_at_serializer_level(self):
        """Serializer-level validation should accept valid name."""
        serializer = CACertificateSerializer(data={'name': VALID_NAME, 'pem_data': 'not-a-cert', 'sha256': 'abc123'})
        # pem_data will fail certificate parsing, but name should not be one of the errors
        serializer.is_valid()
        assert 'name' not in serializer.errors

    def test_grandfather_unchanged_name_on_update(self, ca_certificate):
        """Update that doesn't change invalid name should succeed."""
        CACertificate.objects.filter(pk=ca_certificate.pk).update(name='cert;invalid')
        ca_certificate.refresh_from_db()

        serializer = CACertificateSerializer(instance=ca_certificate, data={'name': 'cert;invalid'}, partial=True)
        assert serializer.is_valid()


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestHTTPPortCleanText:
    """Test CleanTextMixin integration with HTTPPortSerializer."""

    def test_rejects_invalid_name_at_serializer_level(self):
        """Serializer-level validation should reject invalid name."""
        serializer = HTTPPortSerializer(data={'name': DANGEROUS_NAME, 'number': 12345})
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_accepts_valid_name_at_serializer_level(self):
        """Serializer-level validation should accept valid name."""
        serializer = HTTPPortSerializer(data={'name': VALID_NAME, 'number': 12345})
        assert serializer.is_valid()

    def test_grandfather_unchanged_name_on_update(self, http_port):
        """Update that doesn't change invalid name should succeed."""
        HTTPPort.objects.filter(pk=http_port.pk).update(name='port`invalid')
        http_port.refresh_from_db()

        serializer = HTTPPortSerializer(instance=http_port, data={'name': 'port`invalid'}, partial=True)
        assert serializer.is_valid()


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
@pytest.mark.django_db
class TestServiceTypeCleanText:
    """Test CleanTextMixin integration with ServiceTypeSerializer."""

    def test_rejects_invalid_name_at_serializer_level(self):
        """Serializer-level validation should reject invalid name."""
        serializer = ServiceTypeSerializer(data={'name': DANGEROUS_NAME})
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_rejects_invalid_login_path(self):
        """Serializer-level validation should reject dangerous login_path (Tier 2 field)."""
        serializer = ServiceTypeSerializer(data={'name': 'custom-service', 'login_path': DANGEROUS_TEXT})
        assert not serializer.is_valid()
        assert 'login_path' in serializer.errors

    def test_accepts_valid_name_at_serializer_level(self):
        """Serializer-level validation should accept valid name and login_path."""
        serializer = ServiceTypeSerializer(data={'name': 'custom-service', 'login_path': '/v1/auth/session/login/'})
        assert serializer.is_valid()

    def test_grandfather_unchanged_name_on_update(self):
        """Update that doesn't change invalid name should succeed."""
        service_type = ServiceType.objects.create(name='custom-service-grandfather')
        ServiceType.objects.filter(pk=service_type.pk).update(name='type;invalid')
        service_type.refresh_from_db()

        serializer = ServiceTypeSerializer(instance=service_type, data={'name': 'type;invalid'}, partial=True)
        assert serializer.is_valid()
