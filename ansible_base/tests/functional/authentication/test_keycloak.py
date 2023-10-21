from unittest import mock

from django.urls import reverse

# TODO: Figure out how to deal with this because SessionAuthentication remains in aap_gateway_api
from aap_gateway_api.authentication.session import SessionAuthentication


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.keycloak.AuthenticatorPlugin.authenticate")
def test_keycloak_auth_successful(authenticate, unauthenticated_api_client, keycloak_authenticator, user):
    """
    Test that a successful keycloak authentication returns a 200 on the /me endpoint.

    Here we mock the keycloak authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse("me-list")
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authenticator_plugins.keycloak.AuthenticatorPlugin.authenticate")
def test_keycloak_auth_failure(authenticate, unauthenticated_api_client, keycloak_authenticator):
    """
    Test that a failed keycloak authentication returns a 401 on the /me endpoint.

    Here we mock the keycloak authentication backend to return None.
    """
    client = unauthenticated_api_client
    authenticate.return_value = None
    client.login()

    url = reverse("me-list")
    response = client.get(url)
    assert response.status_code == 401
