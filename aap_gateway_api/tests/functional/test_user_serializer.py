from unittest import mock

import pytest
from django.urls import reverse

from aap_gateway_api.models import User
from aap_gateway_api.utils import ENCRYPTED_STRING


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
def test_password_constraints(admin_api_client, user, set_preference, pref_name, pref_value, password, error_substr):
    url = reverse('user-detail', kwargs={'pk': user.id})
    set_preference('local_login', pref_name, pref_value)
    response = admin_api_client.patch(url, {'password': password})
    if error_substr is None:
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert error_substr in response.data['password'][0]


def test_password_constraints_password_is_encrypted_string(admin_api_client, user):
    url = reverse('user-detail', kwargs={'pk': user.id})
    response = admin_api_client.patch(url, {'password': ENCRYPTED_STRING})
    assert response.status_code == 200


def test_password_constraints_password_not_given(admin_api_client, user):
    url = reverse('user-detail', kwargs={'pk': user.id})
    response = admin_api_client.patch(url, {})
    assert response.status_code == 200


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
def test_password_constraints_max_length(admin_api_client, user, password, expected_status):
    password_max_length = User._meta.get_field('password').max_length

    url = reverse('user-detail', kwargs={'pk': user.id})

    response = admin_api_client.patch(url, {'password': password})
    assert response.status_code == expected_status

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
def test_password_constraints_superuser_exemption(logger, admin_api_client, user, set_preference, allow_admins_to_set_insecure, expected_status):
    set_preference('local_login', 'password_min_length', 10)
    set_preference('local_login', 'allow_admins_to_set_insecure', allow_admins_to_set_insecure)
    url = reverse('user-detail', kwargs={'pk': user.id})
    response = admin_api_client.patch(url, {'password': '123456789'})

    assert response.status_code == expected_status

    if expected_status == 200:
        logger.warning.assert_called_with(f'User admin was allowed to save an insecure password for user {user.id}')
    else:
        logger.warning.assert_not_called()
