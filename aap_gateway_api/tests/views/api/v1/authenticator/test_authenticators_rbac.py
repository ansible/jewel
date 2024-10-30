import pytest
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.tests.views.api.v1.conftest import TestPermissionsBase


@pytest.mark.django_db
@pytest.mark.parametrize('endpoint', ['trigger_definition', 'authenticator_plugin'])
class TestAuthenticationReadOnlyPermissions(TestPermissionsBase):
    def test_authenticator_read_only_list(self, endpoint, user_type):
        url = get_relative_url(f"{endpoint}-view")
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200

    def test_authenticator_read_only_options(self, endpoint, user_type):
        url = get_relative_url(f"{endpoint}-view")
        response = self.api_client.options(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is None, f"{endpoint} is read only"


class TestUiAuthPermissions(TestPermissionsBase):
    def test_authenticator_ui_auth_list(self, user_type):
        url = get_relative_url("ui_auth-view")
        response = self.api_client.get(url)

        assert response.status_code == 200


@pytest.mark.django_db
class TestAuthenticatorPermissions(TestPermissionsBase):
    def test_authenticator_list(self, authenticator_local, user_type):
        url = get_relative_url("authenticator-list")
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['count'] > 0

    def test_authenticator_list_options(self, user_type):
        url = get_relative_url("authenticator-list")
        response = self.api_client.options(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        elif user_type == 'platform_auditor':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is None, "POST not allowed for system auditor"
        elif user_type == 'superuser':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is not None, "Create should be enabled for superuser"

    def test_authenticator_detail(self, user_type, authenticator_local):
        url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_local.pk})
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['id'] == authenticator_local.id

    def test_authenticator_detail_options(self, user_type, authenticator_local):
        url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_local.pk})
        response = self.api_client.options(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        elif user_type == 'platform_auditor':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('PUT', None) is None, "read only for system auditor"
        elif user_type == 'superuser':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('PUT', None) is not None, "Update should be allowed for superuser"

    def test_authenticator_update(self, user_type, authenticator_local):
        url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_local.pk})
        data = {"name": "Test Authenticator with updated name"}

        response = self.api_client.patch(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['name'] == data['name']

    def test_authenticator_delete(self, user_type, authenticator_local):
        url = get_relative_url("authenticator-detail", kwargs={"pk": authenticator_local.pk})

        response = self.api_client.delete(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 204
            assert not Authenticator.objects.filter(name=authenticator_local.name).exists()


class TestAuthenticatorMapPermission(TestPermissionsBase):
    def test_authenticator_map_list(self, authenticator_map, user_type):
        url = get_relative_url("authenticatormap-list")
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['count'] == 1

    def test_authenticator_map_list_options(self, user_type):
        url = get_relative_url("authenticatormap-list")
        response = self.api_client.options(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        elif user_type == 'platform_auditor':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is None, "POST not allowed for system auditor"
        elif user_type == 'superuser':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is not None, "Create should be enabled for superuser"

    def test_authenticator_map_detail(self, user_type, authenticator_map):
        url = get_relative_url("authenticatormap-detail", kwargs={"pk": authenticator_map.pk})
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['id'] == authenticator_map.id

    def test_authenticator_map_detail_options(self, user_type, authenticator_map):
        url = get_relative_url("authenticatormap-detail", kwargs={"pk": authenticator_map.pk})
        response = self.api_client.options(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        elif user_type == 'platform_auditor':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('PUT', None) is None, "read only for system auditor"
        elif user_type == 'superuser':
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('PUT', None) is not None, "Update should be allowed for superuser"

    def test_authenticator_map_update(self, user_type, authenticator_map):
        url = get_relative_url("authenticatormap-detail", kwargs={"pk": authenticator_map.pk})
        data = {"name": "Test AuthenticatorMap with updated name"}

        response = self.api_client.patch(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['name'] == data['name']

    def test_authenticator_delete(self, user_type, authenticator_map):
        url = get_relative_url("authenticatormap-detail", kwargs={"pk": authenticator_map.pk})

        response = self.api_client.delete(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 204
            assert not Authenticator.objects.filter(name=authenticator_map.name).exists()
