from unittest import mock
from unittest.mock import patch

import pytest
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.test.client import RequestFactory
from rest_framework import status

from aap_gateway_api.models import User
from aap_gateway_api.serializers.user import PASSWORD_DISABLED, UserSerializer


class TestUserSerializer:
    @pytest.mark.parametrize(
        'pref_name, pref_value, password, error_substr',
        [
            ('password_min_length', 10, '123456789', 'at least 10 characters'),
            ('password_min_length', 10, '1234567890', None),
            ('password_min_digits', 2, 'abcdefgh', 'at least 2 digits'),
            ('password_min_digits', 2, 'abcdefgh123', None),
            ('password_min_upper', 2, 'abcdefgh', 'at least 2 uppercase'),
            ('password_min_upper', 2, 'abcdeFGh', None),
            ('password_min_special', 2, 'abcdefgh', 'at least 2 special'),
            ('password_min_special', 2, '*#()!#(@!', None),
        ],
    )
    def test_password_constraints(self, admin_api_client, user, set_preference, pref_name, pref_value, password, error_substr):
        url = get_relative_url('user-detail', kwargs={'pk': user.id})
        for preference_name in ['password_min_length', 'password_min_digits', 'password_min_upper', 'password_min_special']:
            set_preference('local_login', preference_name, 0)
        set_preference('local_login', pref_name, pref_value)
        response = admin_api_client.patch(url, {'password': password})
        if error_substr is None:
            assert response.status_code == 200
        else:
            assert response.status_code == 400
            assert error_substr in response.data['password'][0]

    @pytest.mark.parametrize(
        'password, expected_password_field',
        [
            ('', PASSWORD_DISABLED),
            (None, ENCRYPTED_STRING),  # This case means password is not given
            (' ', PASSWORD_DISABLED),
            (ENCRYPTED_STRING, ENCRYPTED_STRING),
            ('!ansible123', ENCRYPTED_STRING),
        ],
    )
    def test_password_edge_cases(self, admin_api_client, user, password, expected_password_field):
        url = get_relative_url('user-detail', kwargs={'pk': user.id})
        payload = {'password': password} if password is not None else {}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200
        assert response.json()['password'] == expected_password_field

    @pytest.mark.parametrize(
        'password, expected_status',
        [
            pytest.param(
                'a' * (User._meta.get_field('password').max_length + 1),
                400,
                marks=pytest.mark.xfail(reason='https://github.com/ansible/aap-gateway/pull/72/files#r1344250645'),
            ),
            ('a' * User._meta.get_field('password').max_length, 200),
        ],
        ids=[
            'reject too long password',
            'permit password exactly the max length',
        ],
    )
    def test_password_constraints_max_length(self, admin_api_client, user, password, expected_status):
        password_max_length = User._meta.get_field('password').max_length

        url = get_relative_url('user-detail', kwargs={'pk': user.id})

        response = admin_api_client.patch(url, {'password': password})
        assert response.status_code == expected_status, f'{response.data}'

        if expected_status == 400:
            assert f'Password max length is {password_max_length}' in response.data['password'][0]

    @pytest.mark.parametrize(
        'allow_admins_to_set_insecure, expected_status',
        [
            pytest.param(True, 200, marks=pytest.mark.xfail(reason='https://github.com/ansible/aap-gateway/pull/72/files#r1344234277')),
            (False, 400),
        ],
    )
    @mock.patch('aap_gateway_api.serializers.user.logger')
    def test_password_constraints_superuser_exemption(self, logger, admin_api_client, user, set_preference, allow_admins_to_set_insecure, expected_status):
        set_preference('local_login', 'password_min_length', 10)
        set_preference('local_login', 'allow_admins_to_set_insecure', allow_admins_to_set_insecure)
        url = get_relative_url('user-detail', kwargs={'pk': user.id})
        response = admin_api_client.patch(url, {'password': '123456789'})

        assert response.status_code == expected_status

        if expected_status == 200:
            logger.warning.assert_called_with(f'User admin was allowed to save an insecure password for user {user.id}')
        else:
            logger.warning.assert_not_called()

    def test_users_resource_summary_fields(self, admin_api_client, user):
        url = get_relative_url("user-detail", kwargs={"pk": user.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["summary_fields"]["resource"]["ansible_id"] == user.resource.ansible_id
        assert response.data["summary_fields"]["resource"]["resource_type"] == user.resource.resource_type

    @pytest.mark.parametrize(
        "user,expected_response",
        [
            ('anonymous', False),
            ('regular', False),
            ('super', True),
        ],
    )
    @pytest.mark.django_db
    def test_users_is_superuser_making_request(self, user, expected_response, random_user, admin_user):
        request = RequestFactory().get('./fake_path')
        if user == 'anonymous':
            request.user = AnonymousUser()
        elif user == 'regular':
            request.user = random_user
        elif user == 'super':
            request.user = admin_user

        serializer = UserSerializer(context={'request': request})
        assert serializer.is_superuser_making_request() == expected_response

    @pytest.mark.django_db
    def test_users_is_superuser_making_request_no_context(self):
        serializer = UserSerializer()
        assert serializer.is_superuser_making_request() is False

    def test_validate_password_user_cannot_change(self, system_user, admin_api_client):
        url = get_relative_url('user-detail', kwargs={'pk': system_user.id})
        response = admin_api_client.patch(url, {'password': '123456789'})

        assert response.status_code == 400

    def test_validate_password_user_cannot_change_post(self, admin_api_client):
        url = get_relative_url('user-list')
        response = admin_api_client.post(url, {'username': settings.SYSTEM_USERNAME, 'password': '123456789'})

        assert response.status_code == 400

    def test_authenticators_no_superuser_not_allowed(self, user_api_client, local_authenticator):
        url = get_relative_url('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'authenticator_uid': 'ronda', 'password': 'asdf1234'}
        response = user_api_client.post(url, payload)
        assert response.status_code == 403, response.json()

    def test_authenticator_validation_no_changes(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'a',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_delete_authenticator(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [],
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_add_authenticator(self, admin_api_client, local_authenticator, random_user):
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': random_user.username,
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_add_multiple_authenticators(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id, ldap_authenticator.id],
            'authenticator_uid': random_user.username,
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400

    def test_add_authenticator_conflicting_uid_on_new_authenticator(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        other_user = User.objects.create(username='testing')
        AuthenticatorUser.objects.create(user=other_user, provider=ldap_authenticator, uid='a')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [ldap_authenticator.id],
            'authenticator_uid': 'a',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400
        assert 'authenticators' in response.json()
        assert 'authenticator_uid' in response.json()

    def test_add_authenticator_conflicting_uid_on_same_authenticator(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        other_user = User.objects.create(username='testing')
        AuthenticatorUser.objects.create(user=other_user, provider=local_authenticator, uid='b')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'b',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400
        assert 'authenticator_uid' in response.json()

    def test_update_user_with_conflicting_authenticator_uid_fails(self, admin_api_client, admin_user, local_authenticator):
        another_user = User.objects.create(username='anotheruser', email='anotheruser@example.com')
        AuthenticatorUser.objects.create(user=another_user, provider=local_authenticator, uid='conflictuid')

        url = get_relative_url('user-detail', kwargs={'pk': admin_user.id})
        payload = {'authenticators': [local_authenticator.id], 'authenticator_uid': 'conflictuid', 'username': 'testuser', 'password': 'password'}
        response = admin_api_client.patch(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'authenticator_uid' in response.json()
        assert 'already in use' in response.json()['authenticator_uid'][0]

    def test_create_user_with_empty_authenticator_uid(self, admin_api_client, local_authenticator):
        payload = {
            'username': 'new_user',
            'email': 'newuser@example.com',
            'authenticators': [local_authenticator.id],
            'authenticator_uid': '',
        }

        response = admin_api_client.post('/api/gateway/v1/users/', payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert 'authenticator_uid' in response.data, "Validation error should mention authenticator_uid"

    def test_partial_update_user_with_empty_authenticator_uid(self, admin_api_client, random_user, local_authenticator):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid="initial_uid")
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})

        payload = {
            'first_name': 'NewFirstName',
            'last_name': 'NewLastName',
            'authenticators': [local_authenticator.id],
            'authenticator_uid': '',
        }

        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert 'authenticator_uid' in response.data, "Validation error should mention authenticator_uid"

    def test_update_user_without_authenticator_uid(self, admin_api_client, random_user, local_authenticator):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid="initial_uid")
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})

        payload = {
            'first_name': 'NewFirstName',
            'last_name': 'NewLastName',
            'authenticators': [local_authenticator.id],
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert 'authenticator_uid' in response.data
        assert 'cannot be empty' in str(response.data['authenticator_uid'])

    def test_update_user_without_changing_authenticators(self, admin_api_client, random_user, local_authenticator):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid="initial_uid")
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})

        payload = {
            'first_name': 'AnotherName',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK, response.data
        random_user.refresh_from_db()
        assert random_user.first_name == 'AnotherName'
        assert random_user.authenticator_users.first().uid == 'initial_uid', "Authenticator UID should not change if authenticators are not in payload"

    def test_remove_all_authenticators_with_uid(self, admin_api_client, random_user, local_authenticator):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='existing_uid')

        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [],  # Removing all authenticators
            'authenticator_uid': 'some_uid',  # Providing a UID when it should be empty
        }

        response = admin_api_client.put(url, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert "should be empty when removing" in str(response.data.get('authenticator_uid')), response.data

    def test_patch_user_with_invalid_authenticator_ids_returns_error(self, admin_api_client, admin_user, local_authenticator):
        url = get_relative_url('user-detail', kwargs={'pk': admin_user.id})
        payload = {'authenticators': [local_authenticator.id, 9999], 'username': 'testuser', 'authenticator_uid': 'testuid', 'password': 'password'}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert '"9999" is not a valid choice.' in response.json()['authenticators'][0]  # We rely on the built-in check

    def test_create_user_with_authenticator(self, admin_api_client, local_authenticator):
        url = get_relative_url('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'authenticator_uid': 'ronda', 'password': 'asdf1234'}
        response = admin_api_client.post(url, payload)
        assert response.status_code == 201, response.json()

    def test_create_user_with_authenticator_no_uid(self, admin_api_client, local_authenticator):
        url = get_relative_url('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'password': 'asdf1234'}
        response = admin_api_client.post(url, payload)
        assert response.status_code == 400, response.json()
        assert 'authenticator_uid' in response.json()

    def test_cant_change_uid_if_multiple_authenticators_with_diff_uid(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        AuthenticatorUser.objects.create(user=random_user, provider=ldap_authenticator, uid='b')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticator_uid': 'c',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400
        assert 'authenticator_uid' in response.json()

    def test_delete_authenticator_from_multiple(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        AuthenticatorUser.objects.create(user=random_user, provider=ldap_authenticator, uid='b')
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200, response.data
        assert response.json()['authenticators'] == [1]

    def test_managed_field_unsetable_through_api(self, admin_api_client, random_user):
        """Test to ensure user.managed cannot be set to true via the API."""
        assert random_user.managed is False
        url = get_relative_url("user-detail", kwargs={"pk": random_user.pk})
        response = admin_api_client.get(url)
        assert response.data['managed'] is False
        response = admin_api_client.patch(url, data={"managed": True})
        assert response.status_code == 200
        assert response.data["managed"] is False

    @pytest.mark.django_db
    def test_managed_field_cant_be_changed_to_false(self, admin_api_client):
        """Test to ensure that user.managed can be set to true via command line but not changed"""
        user = User.objects.create(username="testing", managed=True)
        user.refresh_from_db()
        assert user.managed is True
        url = get_relative_url("user-detail", kwargs={"pk": user.pk})
        response = admin_api_client.get(url)
        assert response.data['managed'] is True
        response = admin_api_client.patch(url, data={"managed": False})
        assert response.status_code == 200
        assert response.data["managed"] is True

    @pytest.mark.django_db
    def test_user_password_change_does_not_reset_session(self, random_user, user_api_client):
        user_api_client.login(username=random_user.username, password='password')
        url = get_relative_url("user-detail", kwargs={"pk": random_user.pk})
        payload = {'password': 'asdf1234'}
        response = user_api_client.patch(url, payload)
        assert response.status_code == 200, response.json()
        response = user_api_client.get(url)
        assert response.status_code == 200, response.json()

    def test_non_superuser_cant_view_user_detail(self, user_api_client, random_user):
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        response = user_api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_non_superuser_cant_change_authenticators(self, user_api_client, random_user, local_authenticator):
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'newuid',
        }
        response = user_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        # The current implementation seems to restrict non-superusers from accessing user details entirely

    def test_authenticator_uid_not_accessible_to_non_superuser(self, user_api_client, random_user):
        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        response = user_api_client.patch(url, {'authenticator_uid': 'new_uid'})

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestUsernameValidation:

    def _create_user(self, admin_api_client, username, password, authenticator_id, authenticator_uid):
        """Helper function to create a user via the API."""
        url = get_relative_url('user-list')
        payload = {
            'username': username,
            'password': password,
            'authenticators': [authenticator_id],
            'authenticator_uid': authenticator_uid,
        }
        response = admin_api_client.post(url, payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()['id']

    def _change_username(self, admin_api_client, user_id, new_username):
        """Helper function to change the username via the API."""
        url = get_relative_url('user-detail', kwargs={'pk': user_id})
        response = admin_api_client.patch(url, {'username': new_username})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response

    def _get_user(self, admin_api_client, user_id):
        """Helper function to retrieve a user via the API."""
        url = get_relative_url('user-detail', kwargs={'pk': user_id})
        response = admin_api_client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response

    def _assert_username_and_uid(self, user_id, expected_username, expected_uid):
        """Helper function to assert the username and authenticator UID."""
        user = User.objects.get(id=user_id)
        auth_user = AuthenticatorUser.objects.get(user_id=user_id)
        assert user.username == expected_username, f"Expected username '{expected_username}', got '{user.username}'"
        assert auth_user.uid == expected_uid, f"Expected UID '{expected_uid}', got '{auth_user.uid}'"

    def test_allow_username_change_when_no_conflict(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'testuser', 'password123', local_authenticator.id, 'testuser')
        new_username = 'testuser_new'
        self._change_username(admin_api_client, user_id, new_username)
        self._assert_username_and_uid(user_id, new_username, new_username)
        response = self._get_user(admin_api_client, user_id)
        assert response.data['username'] == new_username
        assert response.data['authenticator_uid'] == new_username

    def test_reject_username_change_when_conflict_exists(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'testuser', 'password123', local_authenticator.id, 'testuser')

        with patch('aap_gateway_api.serializers.user.determine_username_from_uid') as mock_determine:
            mock_determine.return_value = 'conflicting_username'
            url = get_relative_url('user-detail', kwargs={'pk': user_id})
            response = admin_api_client.patch(url, {'username': 'new_testuser'})
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert "does not comply with the rules for authenticator" in str(response.data['username'])

    def test_update_user_with_new_username_via_api(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'localuser', 'testpassword123', local_authenticator.id, 'localuser')
        new_username = 'localuser_new'
        self._change_username(admin_api_client, user_id, new_username)

        user_data = self._get_user(admin_api_client, user_id).data
        update_payload = {
            'username': new_username,
            'authenticators': user_data['authenticators'],
            'authenticator_uid': user_data['authenticator_uid'],
        }
        url = get_relative_url('user-detail', kwargs={'pk': user_id})
        response = admin_api_client.put(url, update_payload)
        assert response.status_code == status.HTTP_200_OK, f"Failed to update user: {response.data}"

    def test_create_and_change_username_twice(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'localuser', 'testpassword123', local_authenticator.id, 'localuser')
        first_new_username = 'localuser_new'
        self._change_username(admin_api_client, user_id, first_new_username)
        second_new_username = 'localuser_newer'
        self._change_username(admin_api_client, user_id, second_new_username)
        self._assert_username_and_uid(user_id, second_new_username, second_new_username)

    def test_username_change_local_auth(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'local-user', 'password789', local_authenticator.id, 'local-user')
        user = User.objects.get(id=user_id)
        assert user.get_authenticator_uids() == ['local-user']
        self._change_username(admin_api_client, user_id, 'new-local-user')
        user.refresh_from_db()
        assert user.username == 'new-local-user'
        assert user.get_authenticator_uids() == ['new-local-user']

    def test_reuse_of_old_username_after_change(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'local-user', 'password789', local_authenticator.id, 'local-user')
        self._change_username(admin_api_client, user_id, 'new-local-user')

        # Attempt to reuse the old username
        new_user_id = self._create_user(admin_api_client, 'local-user', 'password101', local_authenticator.id, 'local-user')
        assert new_user_id is not None

    def test_allow_username_change_for_non_local_authenticator(self, admin_api_client, ldap_authenticator):
        user_id = self._create_user(admin_api_client, 'ldapuser', 'password123', ldap_authenticator.id, 'ldapuser')
        new_username = 'new_ldapuser'
        self._change_username(admin_api_client, user_id, new_username)
        response = self._get_user(admin_api_client, user_id)
        assert response.data['username'] == new_username

    def test_allow_username_update_with_same_value(self, admin_api_client, local_authenticator):
        user_id = self._create_user(admin_api_client, 'testuser', 'password123', local_authenticator.id, 'testuser')
        response = self._change_username(admin_api_client, user_id, 'testuser')
        assert response.data['username'] == 'testuser'

    def test_username_change_with_multiple_authenticators(self, admin_api_client, random_user, local_authenticator, ldap_authenticator):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='local_username')
        AuthenticatorUser.objects.create(user=random_user, provider=ldap_authenticator, uid='ldap_username')

        url = get_relative_url('user-detail', kwargs={'pk': random_user.id})
        payload = {'authenticator_uid': 'new_local_username', 'authenticators': [local_authenticator.id, ldap_authenticator.id]}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert "UID changes are not supported" in str(response.data['authenticator_uid'][0])

        random_user.refresh_from_db()
        assert random_user.username == random_user.username  # No change expected
        assert AuthenticatorUser.objects.get(user=random_user, provider=local_authenticator).uid == 'local_username'
        assert AuthenticatorUser.objects.get(user=random_user, provider=ldap_authenticator).uid == 'ldap_username'


@pytest.mark.django_db
class TestUserUpdateRollbackScenario:

    def _create_user_with_authenticator(self, user, authenticator, uid="initial_uid"):
        """Helper function to create an AuthenticatorUser instance."""
        AuthenticatorUser.objects.create(user=user, provider=authenticator, uid=uid)
        return user

    def _assert_user_unchanged(self, user, initial_values):
        """Helper function to assert that user fields have not changed."""
        user.refresh_from_db()
        for field, initial_value in initial_values.items():
            if field == 'authenticator_uid':
                current_value = user.authenticator_users.first().uid
            elif field == 'password':
                continue  # Skip password check as it's hashed
            else:
                current_value = getattr(user, field)
            assert current_value == initial_value, f"{field} should not have changed due to rollback"
        assert AuthenticatorUser.objects.filter(user=user).count() == 1, "No new AuthenticatorUser should have been created"

    def _test_rollback(self, admin_api_client, user, payload, initial_values):
        """Helper function to handle rollback tests."""
        url = get_relative_url('user-detail', kwargs={'pk': user.id})
        with patch.object(UserSerializer, '_update_users_authenticators', side_effect=Exception("Simulated failure")):
            with pytest.raises(Exception):
                with transaction.atomic():
                    _ = admin_api_client.patch(url, payload)

        self._assert_user_unchanged(user, initial_values)

    def test_update_rollback_on_authenticator_failure(self, admin_api_client, random_user, local_authenticator):
        user = self._create_user_with_authenticator(random_user, local_authenticator)

        initial_values = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'is_superuser': user.is_superuser,
            'authenticator_uid': user.authenticator_users.first().uid,
        }

        payload = {
            'username': 'new_username',
            'first_name': 'New',
            'last_name': 'User',
            'email': 'newuser@example.com',
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'new_username',
        }

        self._test_rollback(admin_api_client, user, payload, initial_values)

    def test_authenticator_changes_rollback(self, admin_api_client, random_user, local_authenticator):
        user = self._create_user_with_authenticator(random_user, local_authenticator)

        new_authenticator = Authenticator.objects.create(name="New Auth", type=local_authenticator.type)
        payload = {
            'authenticators': [new_authenticator.id],
            'authenticator_uid': 'new_uid',
        }

        initial_values = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'is_superuser': user.is_superuser,
            'authenticator_uid': "initial_uid",
        }

        self._test_rollback(admin_api_client, user, payload, initial_values)

    @pytest.mark.parametrize(
        "update_field, update_value",
        [
            ('username', 'new_username'),
            ('email', 'newemail@example.com'),
            ('first_name', 'NewFirstName'),
            ('last_name', 'NewLastName'),
            ('is_superuser', True),
            ('authenticator_uid', 'new_uid'),
            ('password', 'newpassword123'),
        ],
    )
    def test_partial_update_rollback(self, admin_api_client, random_user, local_authenticator, update_field, update_value):
        user = self._create_user_with_authenticator(random_user, local_authenticator)

        initial_values = {
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_superuser': user.is_superuser,
            'authenticator_uid': user.authenticator_users.first().uid,
            'password': user.password,
        }

        payload = {update_field: update_value}
        if update_field == 'authenticator_uid':
            payload['authenticators'] = [local_authenticator.id]

        self._test_rollback(admin_api_client, user, payload, initial_values)

    def test_multiple_field_update_rollback(self, admin_api_client, random_user, local_authenticator):
        user = self._create_user_with_authenticator(random_user, local_authenticator)

        initial_values = {
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_superuser': user.is_superuser,
            'authenticator_uid': user.authenticator_users.first().uid,
        }

        payload = {
            'username': 'new_username',
            'email': 'newemail@example.com',
            'first_name': 'NewFirstName',
            'last_name': 'NewLastName',
            'is_superuser': True,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'new_uid',
        }

        self._test_rollback(admin_api_client, user, payload, initial_values)


@pytest.fixture(scope="function")
def local_user_bad_uid(admin_api_client, local_authenticator, randname):
    url = get_relative_url('user-list')
    username = randname("testuser")
    other_username = randname("testuser")
    payload = {'username': username, 'password': 'password', 'authenticator_uid': other_username, 'authenticators': [local_authenticator.id]}
    response = admin_api_client.post(url, payload)
    assert response.status_code == status.HTTP_201_CREATED

    created_user = User.objects.get(id=response.data["id"])

    yield created_user

    created_user.delete()


@pytest.mark.django_db
class TestUserCrossFieldValidation:
    def test_no_authenticators_no_uid(self, admin_api_client, admin_user):
        url = get_relative_url('user-detail', kwargs={'pk': admin_user.id})
        payload = {'username': 'testuser', 'password': 'password'}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK

    def test_local_authenticator_bad_uid(self, admin_api_client, local_user_bad_uid, local_authenticator):
        """
        Test updating another local authenticator user's authenticator_uid, make sure it coerces back to username
        """
        # Test created user authenticator_uid correct
        authenticator_uid = AuthenticatorUser.objects.get(user=local_user_bad_uid, provider=local_authenticator).uid
        assert authenticator_uid == local_user_bad_uid.username, "User authenticator_uid is not corrected on creation for local authenticator users"

        # Test update of the other user
        url = get_relative_url('user-detail', kwargs={'pk': local_user_bad_uid.id})
        payload = {'authenticator_uid': 'different_uid'}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK
        assert (
            response.data["authenticator_uid"] == local_user_bad_uid.username
        ), "User authenticator_uid is not corrected on update for local authenticator users"

    def test_uid_without_authenticators(self, admin_api_client, admin_user):
        url = get_relative_url('user-detail', kwargs={'pk': admin_user.id})
        payload = {'authenticator_uid': 'newadmin', 'username': 'testuser', 'password': 'password'}
        response = admin_api_client.patch(url, payload)
        assert response.status_code == status.HTTP_200_OK
        # The current implementation allows setting a UID without specifying authenticators.
        # This is handled in the validate_authenticator_uid method, which only checks for superuser permissions
        # and doesn't require authenticators to be present.
