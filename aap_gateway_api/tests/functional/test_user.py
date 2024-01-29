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


def test_user_teams_associate(admin_api_client, user, team, team_1, team_2):
    """
    Test that we can associate teams with an user.
    """
    url = reverse("user-teams-associate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk, team_2.pk]})
    assert response.status_code == 204
    assert user.teams.count() == 2
    assert team_1 in user.teams.all()
    assert team_2 in user.teams.all()


def test_user_teams_associate_twice_noop(admin_api_client, user, team, team_1, team_2):
    """
    Test that associating the same teams twice is a no-op.
    """
    url = reverse("user-teams-associate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk, team_2.pk]})
    assert response.status_code == 204
    assert user.teams.count() == 2
    assert team_1 in user.teams.all()
    assert team_2 in user.teams.all()

    # Associate the same teams again - should be a no-op
    response = admin_api_client.post(url, data={"instances": [team_1.pk, team_2.pk]})
    assert response.status_code == 204
    assert user.teams.count() == 2
    assert team_1 in user.teams.all()
    assert team_2 in user.teams.all()


def test_user_teams_associate_nonexistent(admin_api_client, user, team):
    """
    Test that we can't associate a nonexistent team with an user.
    """
    url = reverse("user-teams-associate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [team.pk, 999]})
    assert response.status_code == 400
    assert user.teams.count() == 0


def test_user_teams_associate_unauthenticated(unauthenticated_api_client, user, team):
    """
    Test that we can't associate an team with an user if we're not authenticated.
    """
    url = reverse("user-teams-associate", kwargs={"pk": user.pk})
    response = unauthenticated_api_client.post(url, data={"instances": [team.pk]})
    assert response.status_code == 401
    assert user.teams.count() == 0


def test_user_teams_disassociate(admin_api_client, user, team, team_1, team_2):
    """
    Test that we can disassociate teams from an user.
    """
    url = reverse("user-teams-associate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk, team_2.pk]})
    assert response.status_code == 204
    assert user.teams.count() == 2
    assert team_1 in user.teams.all()
    assert team_2 in user.teams.all()

    # Disassociate the teams
    url = reverse("user-teams-disassociate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk]})
    assert response.status_code == 204
    assert user.teams.count() == 1
    assert team_1 not in user.teams.all()
    assert team_2 in user.teams.all()


def test_user_organizations_associate(admin_api_client, organization, user):
    """
    Test that we can associate users with an organization (from user endpoint).
    """
    url = reverse("user-organizations-associate", kwargs={"pk": user.pk})
    response = admin_api_client.post(url, data={"instances": [organization.pk]})
    assert response.status_code == 204
    assert user.organizations.count() == 1
    assert organization in user.organizations.all()
