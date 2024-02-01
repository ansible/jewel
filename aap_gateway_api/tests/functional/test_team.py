import pytest
from django.urls import reverse


@pytest.mark.parametrize(
    "description",
    [
        "A test team, which is thusly described.",
        "",
        None,
    ],
)
def test_teams_create_description_is_optional(admin_api_client, randname, organization, description):
    url = reverse("team-list")
    random_name = randname("Test Team")
    data = {"name": random_name, "organization": organization.id}
    if description is not None:
        data["description"] = description
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == random_name
    if description is not None:
        assert results[0]["description"] == description
    else:
        assert results[0]["description"] == ""


def test_teams_parents_works(admin_api_client, randname, organization, team):
    url = reverse("team-list")
    random_name = randname("Test Team")
    data = {"name": random_name, "organization": organization.id, "parents": [team.id]}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 2
    assert set(result["name"] for result in results) == {random_name, team.name}
    parents_by_name = {}
    for result in results:
        parents_by_name[result["name"]] = result["parents"]
    assert parents_by_name == {random_name: [team.id], team.name: []}


def test_teams_users_association(admin_api_client, team, user):
    """
    Test that we can (dis)associate users with a team (from the team side).
    """
    assert team.users.count() == 0

    url = reverse("team-users-associate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.users.count() == 1
    assert team.users.first() == user

    url = reverse("team-users-disassociate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.users.count() == 0


def test_teams_admins_association(admin_api_client, team, user):
    """
    Test that we can (dis)associate admins with a team (from the team side).
    """
    assert team.admins.count() == 0

    url = reverse("team-admins-associate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.admins.count() == 1
    assert team.admins.first() == user

    url = reverse("team-admins-disassociate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.admins.count() == 0


def test_teams_parents_association(admin_api_client, team, team_1):
    """
    Test that we can (dis)associate a parent team with a team.
    """
    assert team.parents.count() == 0

    url = reverse("team-parents-associate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk]})
    assert response.status_code == 204
    assert team.parents.count() == 1
    assert team.parents.first() == team_1

    url = reverse("team-parents-disassociate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [team_1.pk]})
    assert response.status_code == 204
    assert team.parents.count() == 0
