import uuid
from datetime import datetime, timedelta
from unittest import mock

import jwt
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from aap_gateway_api.models import ServiceCluster, ServiceKey, ServiceType

User = get_user_model()


@pytest.mark.django_db
class TestJWTClaimsView:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', email='test@example.com', first_name='Test', last_name='User')
        self.service_type, _ = ServiceType.objects.get_or_create(name='test-service-type')
        self.service_cluster = ServiceCluster.objects.create(name='test-service', service_id=uuid.uuid4(), service_type=self.service_type)
        self.service_key = ServiceKey.objects.create(service_cluster=self.service_cluster, algorithm='HS256', is_active=True)
        self.service_key.refresh_from_db()
        self.service_user = User.objects.create_user(username='service-user', email='service@example.com')

    def create_service_token(self, user_ansible_id=None):
        """Helper method to create a valid service token"""
        payload = {
            'iss': str(self.service_cluster.service_id),
            'exp': (datetime.now() + timedelta(hours=1)).timestamp(),
        }
        if user_ansible_id:
            payload['sub'] = user_ansible_id
        return jwt.encode(payload, self.service_key.secret, algorithm=self.service_key.algorithm)

    def get_jwt_claims_url(self, user_ansible_id=None):
        """Helper method to construct JWT claims URL"""
        ansible_id = user_ansible_id or str(self.user.resource.ansible_id)
        return reverse('jwt-claims-view', kwargs={'user_ansible_id': ansible_id})

    def make_authenticated_request(self, url, auth_token=None, user=None):
        """Helper method to make authenticated requests"""
        if auth_token:
            return self.client.get(url, HTTP_X_ANSIBLE_SERVICE_AUTH=auth_token)
        elif user:
            self.client.force_authenticate(user=user)
            return self.client.get(url)
        return self.client.get(url)

    def assert_valid_jwt_claims_response(self, response):
        """Helper method to validate JWT claims response structure"""
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        expected_keys = ['objects', 'object_roles', 'global_roles', 'claims_hash']
        for key in expected_keys:
            assert key in data, f"Expected key '{key}' not found in JWT claims"

        assert isinstance(data['objects'], dict)
        assert isinstance(data['object_roles'], dict)
        assert isinstance(data['global_roles'], list)

        # Verify objects structure
        assert 'organization' in data['objects']
        assert 'team' in data['objects']
        assert isinstance(data['objects']['organization'], list)
        assert isinstance(data['objects']['team'], list)

        # Verify claims_hash is a 64-character hex string (SHA-256)
        assert isinstance(data['claims_hash'], str)
        assert len(data['claims_hash']) == 64
        assert all(c in '0123456789abcdef' for c in data['claims_hash'])

        return data

    def test_jwt_claims_with_valid_service_token(self):
        """Test that the endpoint returns JWT claims for a valid user with service token auth"""
        url = self.get_jwt_claims_url()
        service_token = self.create_service_token(user_ansible_id=str(self.service_user.resource.ansible_id))
        response = self.make_authenticated_request(url, auth_token=service_token)
        self.assert_valid_jwt_claims_response(response)

    def test_jwt_claims_user_not_found(self):
        """Test that the endpoint returns 404 for non-existent user"""
        non_existent_id = str(uuid.uuid4())
        url = self.get_jwt_claims_url(user_ansible_id=non_existent_id)
        service_token = self.create_service_token(user_ansible_id=str(self.service_user.resource.ansible_id))
        response = self.make_authenticated_request(url, auth_token=service_token)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert 'error' in data
        assert non_existent_id in data['error']

    @pytest.mark.parametrize(
        "auth_method,expected_status",
        [
            (None, status.HTTP_401_UNAUTHORIZED),
            ("invalid.jwt.token", status.HTTP_401_UNAUTHORIZED),
        ],
    )
    def test_jwt_claims_authentication_failures(self, auth_method, expected_status):
        """Test that the endpoint handles authentication failures correctly"""
        url = self.get_jwt_claims_url()
        response = self.make_authenticated_request(url, auth_token=auth_method)
        assert response.status_code == expected_status

    def test_jwt_claims_hash_deterministic(self):
        """Test that the claims hash is deterministic for the same user"""
        url = self.get_jwt_claims_url()
        service_token = self.create_service_token(user_ansible_id=str(self.service_user.resource.ansible_id))

        response1 = self.make_authenticated_request(url, auth_token=service_token)
        response2 = self.make_authenticated_request(url, auth_token=service_token)

        data1 = self.assert_valid_jwt_claims_response(response1)
        data2 = self.assert_valid_jwt_claims_response(response2)

        assert data1['claims_hash'] == data2['claims_hash']

    @pytest.mark.parametrize(
        "is_superuser,expected_status",
        [
            (True, status.HTTP_200_OK),
            (False, status.HTTP_403_FORBIDDEN),
        ],
    )
    def test_jwt_claims_user_access_permissions(self, is_superuser, expected_status):
        """Test user access permissions based on superuser status"""
        url = self.get_jwt_claims_url()
        test_user = User.objects.create_user(username=f'testuser_{is_superuser}', email=f'test_{is_superuser}@example.com', is_superuser=is_superuser)

        response = self.make_authenticated_request(url, user=test_user)

        assert response.status_code == expected_status

        if expected_status == status.HTTP_200_OK:
            self.assert_valid_jwt_claims_response(response)

    @mock.patch('aap_gateway_api.views.api.v1.jwt_claims.get_user_claims')
    def test_jwt_claims_error_handling(self, mock_get_claims):
        """Test that the endpoint handles errors gracefully"""
        url = self.get_jwt_claims_url()
        mock_get_claims.side_effect = Exception("Claims generation failed")
        service_token = self.create_service_token(user_ansible_id=str(self.service_user.resource.ansible_id))

        response = self.make_authenticated_request(url, auth_token=service_token)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        data = response.json()
        assert 'error' in data
        assert "Failed to generate JWT claims" in data['error']

    @pytest.mark.parametrize(
        "resource_actions,expected_status,should_include_actions",
        [
            (['list', 'retrieve', 'create'], status.HTTP_200_OK, True),
            (['list', 'create'], status.HTTP_403_FORBIDDEN, False),  # Missing 'retrieve'
        ],
    )
    def test_jwt_claims_service_token_permissions(self, resource_actions, expected_status, should_include_actions):
        """Test service token permissions based on resource_api_actions"""
        url = self.get_jwt_claims_url()
        service_token = self.create_service_token(user_ansible_id=str(self.service_user.resource.ansible_id))

        with mock.patch('aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication.authenticate') as mock_auth:
            mock_user = mock.Mock()
            mock_user.is_authenticated = True
            mock_user.is_superuser = False
            mock_user.resource_api_actions = resource_actions
            mock_auth.return_value = (mock_user, 'ServiceTokenAuthentication')

            response = self.make_authenticated_request(url, auth_token=service_token)

            assert response.status_code == expected_status

            if should_include_actions and response.status_code == status.HTTP_200_OK:
                data = response.json()
                if 'resource_api_actions' in data:
                    assert set(data['resource_api_actions']) == set(resource_actions)  # order-agnostic check for extra safety)
