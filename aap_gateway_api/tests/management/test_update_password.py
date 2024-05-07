import pytest
from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_update_password_command(user_factory):
    """Validate the update_password command changes a user's password."""

    # check basic functionality ...
    test_user = user_factory("test_user_999")
    call_command('update_password', f'--username={test_user.username}', '--password=redhat1234')
    test_user.refresh_from_db()
    assert check_password('redhat1234', test_user.password)


@pytest.mark.django_db
def test_update_password_command_missing_password(user_factory):
    """Validate the update_password command handles a missing password kwarg."""

    # validate it blows up with a missing username
    with pytest.raises(CommandError):
        call_command('update_password', '--username=foobar1234')


@pytest.mark.django_db
def test_update_password_command_missing_username(user_factory):
    """Validate the update_password command handles a missing username kwarg."""

    # validate it blows up with a missing username
    with pytest.raises(CommandError):
        call_command('update_password', '--password=redhat1234')


@pytest.mark.django_db
def test_update_password_command_invalid_username(user_factory):
    """Validate the update_password command handles an invalid username."""

    from aap_gateway_api.models.user import User

    # validate it blows up with an invalid username
    with pytest.raises(User.DoesNotExist):
        call_command('update_password', '--username=foobar1234', '--password=redhat1234')
