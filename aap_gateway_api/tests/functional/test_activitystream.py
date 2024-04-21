from django.urls import reverse


def test_activitystream_gets_logged(admin_api_client, user):
    """
    Ensure that activity stream is properly enabled in the Gateway.
    """
    user.first_name = 'Jane'
    user.save()

    last_entry = user.activity_stream_entries.last()
    assert last_entry.operation == 'update'
    assert last_entry.changes == {'added_fields': {}, 'removed_fields': {}, 'changed_fields': {'first_name': ['', 'Jane']}}

    url = reverse('activitystream-list')
    response = admin_api_client.get(url, data={'order_by': '-created'})
    assert response.status_code == 200, response.data
    assert response.data['count'] > 0
    found_user_entry = False
    expected_changes = {'added_fields': {}, 'removed_fields': {}, 'changed_fields': {'first_name': ['', 'Jane']}}
    for result in response.data['results']:
        if result['content_type_model'] == 'user':
            if result['operation'] == 'update' and result['changes'] == expected_changes:
                found_user_entry = True
    assert found_user_entry is True, "Could not find the expected entry for user"


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
