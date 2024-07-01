from time import sleep

import pytest
from ansible_base.lib.utils.response import get_relative_url


class TestSessionView:
    @pytest.mark.parametrize(
        "client_type,status_code",
        [
            ('admin', 200),
            ('unauth', 401),
            ('user', 200),
        ],
    )
    def test_access_denied_if_not_authenticated(self, client_type, status_code, admin_api_client, unauthenticated_api_client, user_api_client):
        if client_type == 'admin':
            client = admin_api_client
        elif client_type == 'user':
            client = user_api_client
        else:
            client = unauthenticated_api_client

        url = get_relative_url('session-view')
        response = client.get(url)
        assert response.status_code == status_code

    def test_time_changes(self, admin_api_client):
        url = get_relative_url('session-view')
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'expires_in_seconds' in response.json()
        assert 'expires_on' in response.json()
        expires_on = response.json().get('expires_on')
        expires_in_seconds = response.json().get('expires_in_seconds')
        sleep(1)
        # Load the page again
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'expires_in_seconds' in response.json()
        assert 'expires_on' in response.json()
        assert expires_on == response.json().get('expires_on')
        assert expires_in_seconds != response.json().get('expires_in_seconds')

    def test_restart_of_session(self, admin_api_client):
        url = get_relative_url('session-view')
        sleep(1)
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert 'expires_in_seconds' in response.json()
        expires_in_seconds = response.json().get('expires_in_seconds')
        response = admin_api_client.post(url)
        response = admin_api_client.get(url)
        assert 'expires_in_seconds' in response.json()
        assert response.json().get('expires_in_seconds') > expires_in_seconds

    def test_404_if_no_session(self, admin_api_client):
        url = get_relative_url('session-view')
        response = admin_api_client.get(url)
        from django.contrib.sessions.models import Session

        Session.objects.all().delete()
        response = admin_api_client.get(url)
        assert response.status_code == 404
