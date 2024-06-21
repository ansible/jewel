import pytest
from ansible_base.authentication.models import AuthenticatorUser
from django.urls import reverse


@pytest.mark.parametrize(
    "post_format",
    [
        "json",
        "multipart",
    ],
)
def test_user_create(admin_api_client, post_format):
    """
    Test that we can create a new user if we are an admin.
    """
    url = reverse("user-list")
    data = {
        "username": "test_user",
        "password": "test_password",
    }
    response = admin_api_client.post(url, data=data, format=post_format)
    assert response.status_code == 201
    assert response.data['username'] == data['username']
    assert 'authenticators' in response.data['related']


@pytest.mark.parametrize(
    "client_fixture",
    [
        "admin_api_client",
        "platform_auditor_api_client",
        "user_api_client",
        "unauthenticated_api_client",
    ],
)
def test_user_authenticators(request, client_fixture, local_authenticator, ldap_authenticator, user):
    """
    Test that we can list authenticators for a user.
    The action is limited to admins.
    """
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    client = request.getfixturevalue(client_fixture)
    url = reverse("user-authenticators-list", kwargs={"pk": user.pk})
    response = client.get(url)

    if client_fixture == "admin_api_client" or client_fixture == "platform_auditor_api_client":
        assert response.status_code == 200
        assert len(response.data['results']) == 2
        names = [authenticator['name'] for authenticator in response.data['results']]
        assert local_authenticator.name in names
        assert ldap_authenticator.name in names
    elif client_fixture == "user_api_client":
        assert response.status_code == 403
    else:
        assert response.status_code == 401


@pytest.mark.parametrize(
    "client_fixture",
    [
        "admin_api_client",
        "unauthenticated_api_client",
    ],
)
def test_forbidden_user_filters(request, client_fixture):
    fields = ["password"]
    client = request.getfixturevalue(client_fixture)
    for field in fields:
        url = reverse("user-list") + f"?{field}__startswith=argon2$argon2id$v=19$m=102400,t=1,p=1$"
        response = client.get(url)
        if client_fixture == "admin_api_client":
            assert response.status_code == 403
        else:
            assert response.status_code == 401


def test_user_authenticators_bad_pk(admin_api_client):
    url = reverse("user-authenticators-list", kwargs={"pk": '1337'})
    response = admin_api_client.get(url)
    assert response.status_code == 404
