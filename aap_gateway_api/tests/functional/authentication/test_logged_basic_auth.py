import base64
from unittest import mock

from django.urls import reverse

from aap_gateway_api.authentication.basic_auth import LoggedBasicAuthentication


# Patch the logger to ensure we log the correct message
@mock.patch("aap_gateway_api.authentication.basic_auth.logged_basic_auth.logger")
def test_logged_basic_auth(logger, unauthenticated_api_client, organization, admin_user, local_authenticator):
    client = unauthenticated_api_client
    client.credentials(HTTP_AUTHORIZATION="Basic " + base64.b64encode("admin:password".encode("utf-8")).decode("utf-8"))
    url = reverse("organization-list")
    response = client.get(url)
    assert response.status_code == 200
    assert logger.info.call_count == 1
    expected = f"User admin performed a GET to {url} through the API via basic auth"
    assert logger.info.call_args[0][0] == expected


def test_logged_basic_auth_disabled(unauthenticated_api_client, organization, admin_user, settings, set_preference):
    set_preference("proxy", "gateway_basic_auth_enabled", False)

    client = unauthenticated_api_client
    client.credentials(HTTP_AUTHORIZATION="Basic " + base64.b64encode("admin:password".encode("utf-8")).decode("utf-8"))
    url = reverse("organization-list")
    response = client.get(url)
    assert response.status_code == 401


# There is really no better way to do this. I tried. Really hard.
# We can't use the 'settings' fixture here. Because even though DRF gets notified of the change,
# the view already has the old settings as local variables. So we have to patch the view to fix that.
@mock.patch("rest_framework.views.APIView.authentication_classes", [LoggedBasicAuthentication])
def test_logged_basic_auth_invalid(unauthenticated_api_client):
    client = unauthenticated_api_client
    client.credentials(HTTP_AUTHORIZATION="Basic " + base64.b64encode("admin:wrongPassw0rd".encode("utf-8")).decode("utf-8"))
    url = reverse("organization-list")
    response = client.get(url)
    assert response.status_code == 401


@mock.patch("rest_framework.views.APIView.authentication_classes", [LoggedBasicAuthentication])
def test_logged_basic_auth_invalid_disabled(unauthenticated_api_client, set_preference):
    set_preference("proxy", "gateway_basic_auth_enabled", False)
    client = unauthenticated_api_client
    client.credentials(HTTP_AUTHORIZATION="Basic " + base64.b64encode("admin:wrongPassw0rd".encode("utf-8")).decode("utf-8"))
    url = reverse("organization-list")
    response = client.get(url)
    assert response.status_code == 401
