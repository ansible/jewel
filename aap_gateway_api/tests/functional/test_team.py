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
