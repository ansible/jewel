import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize(
    "key, route",
    [("users", "team-users-list"), ("admins", "team-admins-list")],
)
def test_teams_related_fields(admin_api_client, team, key, route):
    url = get_relative_url("team-detail", kwargs={"pk": team.id})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    team = response.data
    assert key in team["related"]
    # assure link is a valid URL
    response = admin_api_client.get(team["related"][key])
    assert response.status_code == 200, response.data


@pytest.mark.parametrize(
    "description",
    [
        "A test team, which is thusly described.",
        "",
        None,
    ],
)
def test_teams_create_description_is_optional(admin_api_client, randname, organization, description):
    url = get_relative_url("team-list")
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


def test_teams_users_association(admin_api_client, team, user):
    """
    Test that we can (dis)associate users with a team (from the team side).
    """
    assert team.users.count() == 0

    url = get_relative_url("team-users-associate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.users.count() == 1
    assert team.users.first() == user

    url = get_relative_url("team-users-disassociate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.users.count() == 0


def test_teams_admins_association(admin_api_client, team, user):
    """
    Test that we can (dis)associate admins with a team (from the team side).
    """
    assert team.admins.count() == 0

    url = get_relative_url("team-admins-associate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.admins.count() == 1
    assert team.admins.first() == user

    url = get_relative_url("team-admins-disassociate", kwargs={"pk": team.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert team.admins.count() == 0


def test_teams_resource_summary_fields(admin_api_client, team):
    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["resource"]["ansible_id"] == team.resource.ansible_id
    assert response.data["summary_fields"]["resource"]["resource_type"] == team.resource.resource_type
