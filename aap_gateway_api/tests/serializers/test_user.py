from unittest import mock

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory
from django.urls import reverse

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
        url = reverse('user-detail', kwargs={'pk': user.id})
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
        url = reverse('user-detail', kwargs={'pk': user.id})
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
                marks=pytest.mark.xfail(reason='see review comments of PR 72'),
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

        url = reverse('user-detail', kwargs={'pk': user.id})

        response = admin_api_client.patch(url, {'password': password})
        assert response.status_code == expected_status, f'{response.data}'

        if expected_status == 400:
            assert f'Password max length is {password_max_length}' in response.data['password'][0]

    @pytest.mark.parametrize(
        'allow_admins_to_set_insecure, expected_status',
        [
            pytest.param(True, 200, marks=pytest.mark.xfail(reason='see review comments of PR 72')),
            (False, 400),
        ],
    )
    @mock.patch('aap_gateway_api.serializers.user.logger')
    def test_password_constraints_superuser_exemption(self, logger, admin_api_client, user, set_preference, allow_admins_to_set_insecure, expected_status):
        set_preference('local_login', 'password_min_length', 10)
        set_preference('local_login', 'allow_admins_to_set_insecure', allow_admins_to_set_insecure)
        url = reverse('user-detail', kwargs={'pk': user.id})
        response = admin_api_client.patch(url, {'password': '123456789'})

        assert response.status_code == expected_status

        if expected_status == 200:
            logger.warning.assert_called_with(f'User admin was allowed to save an insecure password for user {user.id}')
        else:
            logger.warning.assert_not_called()

    def test_users_resource_summary_fields(self, admin_api_client, user):
        url = reverse("user-detail", kwargs={"pk": user.pk})
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
        url = reverse('user-detail', kwargs={'pk': system_user.id})
        response = admin_api_client.patch(url, {'password': '123456789'})

        assert response.status_code == 400

    def test_validate_password_user_cannot_change_post(self, admin_api_client):
        url = reverse('user-list')
        response = admin_api_client.post(url, {'username': settings.SYSTEM_USERNAME, 'password': '123456789'})

        assert response.status_code == 400

    def test_authenticators_no_superuser_not_allowed(self, user_api_client, local_authenticator):
        url = reverse('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'authenticator_uid': 'ronda', 'password': 'asdf1234'}
        response = user_api_client.post(url, payload)
        assert response.status_code == 403, response.json()

    def test_authenticator_validation_no_changes(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'a',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_delete_authenticator(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [],
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_add_authenticator(self, admin_api_client, local_authenticator, random_user):
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': random_user.username,
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200

    def test_add_multiple_authenticators(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        url = reverse('user-detail', kwargs={'pk': random_user.id})
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
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [ldap_authenticator.id],
            'authenticator_uid': 'a',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400
        assert 'authenticators' in response.json()

    def test_add_authenticator_conflicting_uid_on_same_authenticator(self, admin_api_client, local_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        other_user = User.objects.create(username='testing')
        AuthenticatorUser.objects.create(user=other_user, provider=local_authenticator, uid='b')
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
            'authenticator_uid': 'b',
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 400
        assert 'authenticator_uid' in response.json()

    def test_create_user_with_authenticator(self, admin_api_client, local_authenticator):
        url = reverse('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'authenticator_uid': 'ronda', 'password': 'asdf1234'}
        response = admin_api_client.post(url, payload)
        assert response.status_code == 201, response.json()

    def test_create_user_with_authenticator_no_uid(self, admin_api_client, local_authenticator):
        url = reverse('user-list')
        payload = {'username': 'ronda', 'authenticators': [local_authenticator.id], 'password': 'asdf1234'}
        response = admin_api_client.post(url, payload)
        assert response.status_code == 400, response.json()
        assert 'authenticator_uid' in response.json()

    def test_cant_change_uid_if_multiple_authenticators_with_diff_uid(self, admin_api_client, local_authenticator, ldap_authenticator, random_user):
        AuthenticatorUser.objects.create(user=random_user, provider=local_authenticator, uid='a')
        AuthenticatorUser.objects.create(user=random_user, provider=ldap_authenticator, uid='b')
        url = reverse('user-detail', kwargs={'pk': random_user.id})
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
        url = reverse('user-detail', kwargs={'pk': random_user.id})
        payload = {
            'username': random_user.username,
            'authenticators': [local_authenticator.id],
        }
        response = admin_api_client.patch(url, payload)
        assert response.status_code == 200
        assert response.json()['authenticators'] == [1]

    def test_managed_field_unsetable_through_api(self, admin_api_client, random_user):
        """Test to ensure user.managed cannot be set to true via the API."""
        assert random_user.managed is False
        url = reverse("user-detail", kwargs={"pk": random_user.pk})
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
        url = reverse("user-detail", kwargs={"pk": user.pk})
        response = admin_api_client.get(url)
        assert response.data['managed'] is True
        response = admin_api_client.patch(url, data={"managed": False})
        assert response.status_code == 200
        assert response.data["managed"] is True
