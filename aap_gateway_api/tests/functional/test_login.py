from unittest import mock

from django.urls import reverse


@mock.patch("aap_gateway_api.views.api.v1.local_login.logger")
def test_login_post_successful_login(logger, unauthenticated_api_client, admin_user, local_authenticator):
    """
    Test POSTing to the login view (successful login).
    """
    url = reverse("login")
    next_url = reverse("user-list")
    data = {"username": "admin", "password": "password", "next": next_url}
    response = unauthenticated_api_client.post(url, data)
    assert response.status_code == 302
    assert response.url == next_url
    assert response.wsgi_request.user == admin_user
    assert logger.info.call_count == 1
    assert logger.info.call_args[0][0].startswith("User admin logged in from")


@mock.patch("aap_gateway_api.views.api.v1.local_login.logger")
def test_login_post_failed_login(logger, unauthenticated_api_client):
    """
    Test POSTing to the login view (failed login).
    """
    url = reverse("login")
    next_url = reverse("user-list")
    data = {"username": "admin", "password": "wrongPassw0rd", "next": next_url}
    response = unauthenticated_api_client.post(url, data)
    assert response.status_code == 401
    assert response.wsgi_request.user.is_anonymous
    assert logger.warning.call_count == 1
    assert logger.warning.call_args[0][0].startswith("Login failed for user admin from")


@mock.patch("aap_gateway_api.views.api.v1.local_login.logger")
def test_login_post_failed_login_weird_username(logger, unauthenticated_api_client):
    """
    Test POSTing to the login view (failed login, weird username - logged as base64).
    """
    url = reverse("login")
    next_url = reverse("user-list")
    data = {"username": "U$3rn#me!", "password": "wrongPassw0rd", "next": next_url}
    response = unauthenticated_api_client.post(url, data)
    assert response.status_code == 401
    assert response.wsgi_request.user.is_anonymous
    assert logger.warning.call_count == 1
    logged_msg = logger.warning.call_args[0][0]
    assert logged_msg.startswith("Login failed for user (base64) b'VSQzcm4jbWUh' from")


def test_login_get_accept_html(unauthenticated_api_client):
    """
    Test GETing the login view.
    """
    url = reverse("login")
    response = unauthenticated_api_client.get(url, HTTP_ACCEPT="text/html")
    assert response.status_code == 200
    assert response.template_name == ["rest_framework/login.html"]


def test_login_get_accept_unknown(unauthenticated_api_client):
    """
    Test GETing the login view with an unknown Accept header.
    """
    url = reverse("login")
    response = unauthenticated_api_client.get(url, HTTP_ACCEPT="application/foobar")
    assert response.status_code == 406


@mock.patch("aap_gateway_api.views.api.v1.local_login.logger")
def test_logout_view(logger, unauthenticated_api_client, admin_user, local_authenticator):
    """
    Test GETing the logout view.
    """
    # First we need to login
    url = reverse("login")
    data = {"username": "admin", "password": "password"}
    response = unauthenticated_api_client.post(url, data)
    assert response.status_code == 302

    # Now we can logout
    url = reverse("logout")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 302
    assert response.wsgi_request.user.is_anonymous
