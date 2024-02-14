import pytest
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


@pytest.mark.parametrize(
    "post_format",
    [
        "json",
        "multipart",
    ],
)
def test_user_create_with_organizations(admin_api_client, organization, post_format):
    """
    Test that we can create a new user with an attached organization if we are an admin.
    """
    from aap_gateway_api.models import User

    url = reverse("user-list")
    data = {
        "username": "test_user",
        "password": "test_password",
        "organizations": [organization.pk],
    }
    response = admin_api_client.post(url, data=data, format=post_format)
    assert response.status_code == 201
    assert response.data['username'] == data['username']
    user = User.objects.get(username=data['username'])
    assert user.organizations.count() == 1
    assert user.organizations.first() == organization


@pytest.mark.parametrize(
    "post_format",
    [
        "json",
        "multipart",
    ],
)
def test_user_create_with_organizations_empty(admin_api_client, organization, post_format):
    """
    Test that we can create a new user with organizations specified as empty if we are an admin.
    """
    url = reverse("user-list")
    data = {
        "username": "test_user",
        "password": "test_password",
        "organizations": [],
    }
    response = admin_api_client.post(url, data=data, format=post_format)
    assert response.status_code == 201
    assert response.data['username'] == data['username']
    # TODO: uncomment once we provide m2m relations in responses
    # assert response.data['organizations'] == []
