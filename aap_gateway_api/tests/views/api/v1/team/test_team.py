from unittest.mock import patch

import pytest
from ansible_base.lib.utils.response import get_relative_url

MOCK_PREF = "aap_gateway_api.utils.views.permissions.get_preference_value"


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


@patch(MOCK_PREF)
def test_team_create_disabled_when_manage_organization_auth_false(mock_pref, user_api_client, organization, randname, user):
    """Team creation is forbidden when MANAGE_ORGANIZATION_AUTH is False and user is not superuser."""
    mock_pref.return_value = False
    organization.add_admin(user)

    url = get_relative_url("team-list")
    data = {"name": randname("Test Team"), "organization": organization.id}
    response = user_api_client.post(url, data=data)

    assert response.status_code == 403


@patch(MOCK_PREF)
def test_team_create_enabled_when_manage_organization_auth_true(mock_pref, user_api_client, organization, randname, user):
    """Team creation works normally when MANAGE_ORGANIZATION_AUTH is True."""
    mock_pref.return_value = True
    organization.add_admin(user)

    url = get_relative_url("team-list")
    random_name = randname("Test Team")
    data = {"name": random_name, "organization": organization.id}
    response = user_api_client.post(url, data=data)

    assert response.status_code == 201
    assert response.data["name"] == random_name


@patch(MOCK_PREF)
def test_team_create_allowed_for_superuser_when_manage_organization_auth_false(mock_pref, admin_api_client, organization, randname):
    """Superusers can create teams even when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False

    url = get_relative_url("team-list")
    random_name = randname("Test Team")
    data = {"name": random_name, "organization": organization.id}
    response = admin_api_client.post(url, data=data)

    assert response.status_code == 201
    assert response.data["name"] == random_name


@patch(MOCK_PREF)
def test_team_delete_disabled_when_manage_organization_auth_false(mock_pref, user_api_client, user, organization, team):
    """Org admin cannot delete a team when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False
    organization.add_admin(user)

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = user_api_client.delete(url)

    assert response.status_code == 403


@patch(MOCK_PREF)
def test_team_delete_allowed_for_superuser_when_manage_organization_auth_false(mock_pref, admin_api_client, team):
    """Superusers can delete teams even when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = admin_api_client.delete(url)

    assert response.status_code == 204


@patch(MOCK_PREF)
def test_team_update_disabled_when_manage_organization_auth_false(mock_pref, user_api_client, user, organization, team):
    """Org admin cannot update a team when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False
    organization.add_admin(user)

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = user_api_client.put(url, data={"name": "Updated Name", "organization": organization.id})

    assert response.status_code == 403


@patch(MOCK_PREF)
def test_team_update_allowed_for_superuser_when_manage_organization_auth_false(mock_pref, admin_api_client, team, organization):
    """Superusers can update teams even when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = admin_api_client.put(url, data={"name": "Updated Name", "organization": organization.id})

    assert response.status_code == 200
    assert response.data["name"] == "Updated Name"


@patch(MOCK_PREF)
def test_team_list_options_org_admin_manage_org_auth_false(mock_pref, user_api_client, user, organization, team):
    """OPTIONS on team list should not show POST action when MANAGE_ORGANIZATION_AUTH is False for org admin."""
    mock_pref.return_value = False
    organization.add_admin(user)

    url = get_relative_url("team-list")
    response = user_api_client.options(url)

    assert response.status_code == 200
    assert response.data.get('actions', {}).get('POST') is None


@patch(MOCK_PREF)
def test_team_list_options_superuser_manage_org_auth_false(mock_pref, admin_api_client):
    """OPTIONS on team list should still show POST for superuser when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False

    url = get_relative_url("team-list")
    response = admin_api_client.options(url)

    assert response.status_code == 200
    assert response.data.get('actions', {}).get('POST') is not None


@patch(MOCK_PREF)
def test_team_detail_options_org_admin_manage_org_auth_false(mock_pref, user_api_client, user, organization, team):
    """OPTIONS on team detail should not show PUT action when MANAGE_ORGANIZATION_AUTH is False for org admin."""
    mock_pref.return_value = False
    organization.add_admin(user)

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = user_api_client.options(url)

    assert response.status_code == 200
    assert response.data.get('actions', {}).get('PUT') is None


@patch(MOCK_PREF)
def test_team_detail_options_superuser_manage_org_auth_false(mock_pref, admin_api_client, team):
    """OPTIONS on team detail should still show PUT for superuser when MANAGE_ORGANIZATION_AUTH is False."""
    mock_pref.return_value = False

    url = get_relative_url("team-detail", kwargs={"pk": team.pk})
    response = admin_api_client.options(url)

    assert response.status_code == 200
    assert response.data.get('actions', {}).get('PUT') is not None
