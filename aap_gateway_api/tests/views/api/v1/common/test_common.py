from collections import OrderedDict
from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.bearer_authentication import BearerAuthentication, BearerTokenValidationError
from ansible_base.lib.utils.response import get_relative_url
from oauthlib.common import generate_token


@pytest.mark.django_db
@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_ensure_oauth2_application_tokens_authenticate(token, expected, oauth2_admin_access_token, admin_user, unauthenticated_api_client):
    url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})
    token = oauth2_admin_access_token[1] if token == 'fixture' else generate_token()
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['username'] == admin_user.username


@pytest.mark.django_db
def test_resource_views_keep_generic_challenge_without_bearer_credential(admin_user, unauthenticated_api_client):
    """Gateway keeps its browser-safe challenge when no Bearer credential is supplied."""
    url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})

    response = unauthenticated_api_client.get(url)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer realm=api authorization_url=/o/authorize/"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("reason", "challenge"),
    [
        ("invalid", 'Bearer realm="api", error="invalid_token"'),
        ("expired", 'Bearer realm="api", error="invalid_token", error_description="The access token expired"'),
        (
            "provider_unavailable",
            'Bearer realm="api", error="invalid_token", error_description="Authentication service unavailable"',
        ),
    ],
)
def test_resource_views_preserve_dab_bearer_failure_challenge(reason, challenge, admin_user, unauthenticated_api_client):
    """The Gateway resource mixin must not replace DAB's safe RFC 6750 response."""
    api_authenticator = Mock()
    api_authenticator.authenticate.side_effect = BearerTokenValidationError(reason)
    url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(1, api_authenticator)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        response = unauthenticated_api_client.get(url, headers={"Authorization": "Bearer invalid-external-token"})

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == challenge
    assert "invalid-external-token" not in response["WWW-Authenticate"]
