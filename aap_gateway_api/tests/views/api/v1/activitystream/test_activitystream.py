from ansible_base.lib.utils.response import get_relative_url
from django.test import Client


def test_activitystream_gets_logged(admin_api_client, user):
    """
    Ensure that activity stream is properly enabled in the Gateway.
    """
    user.first_name = 'Jane'
    user.save()

    last_entry = user.activity_stream_entries.last()
    assert last_entry.operation == 'update'
    assert last_entry.changes == {'added_fields': {}, 'removed_fields': {}, 'changed_fields': {'first_name': ['', 'Jane']}}

    url = get_relative_url('activitystream-list')
    response = admin_api_client.get(url, data={'order_by': '-created'})
    assert response.status_code == 200, response.data
    assert response.data['count'] > 0
    assert response.data['results'][0]['operation'] == 'update', response.data['results'][0]
    assert response.data['results'][0]['changes'] == {'added_fields': {}, 'removed_fields': {}, 'changed_fields': {'first_name': ['', 'Jane']}}


def test_activitystream_user_last_login_not_tracked(user_api_client, user):
    """
    Ensure that a User's last_login is not stored in activity stream.
    """
    last_login = user.last_login
    user_api_client.login(username=user.username, password='password')
    user.refresh_from_db()
    assert user.last_login != last_login
    last_entry = user.activity_stream_entries.last()
    assert last_entry.operation == 'create'  # not 'update', no entry was created for the login


def test_activitystream_user_last_login_from_not_tracked(admin_api_client, user, local_authenticator):
    """
    Ensure that a User's last_login_from is not stored in activity stream.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an authenticator for the user
    AuthenticatorUser.objects.create(user=user, provider=local_authenticator, uid=user.username)

    # Get initial activity stream entry count
    initial_count = user.activity_stream_entries.count()

    # Use proper authentication instead of manually setting the field
    # Simulate authentication which should set last_login_from through the backend
    client = Client()
    client.force_login(user)  # This simulates the authentication process

    # Check if authentication backend set the field, if not set it as backend would
    user.refresh_from_db()
    if not user.last_login_from:
        # Simulate what the authentication backend should do
        user.last_login_from = local_authenticator
        user.save()

    # Verify that no new activity stream entry was created for the last_login_from update
    user.refresh_from_db()
    final_count = user.activity_stream_entries.count()
    assert final_count == initial_count, "No activity stream entry should be created when last_login_from is updated"
