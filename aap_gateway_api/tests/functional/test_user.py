from django.urls import reverse


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
