def api_get_and_assert(url, api_client, expected_objects, order_by="name"):
    response = api_client.get(url, {"order_by": order_by})
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == len(expected_objects)
    for i in range(len(expected_objects)):
        assert results[i]["name"] == expected_objects[i].name, f"result: {results[i]['name']}, expected: {expected_objects[i].name}"


def default_visible_organizations(organizations):
    return organizations[0:5]


def default_changeable_organizations(organizations):
    return [organizations[1], organizations[2], organizations[4]]


def default_visible_teams(teams, organizations):
    """RBAC: Org Members don't see Team Members"""
    return (
        [teams[organizations[0]][0], teams[organizations[1]][0], teams[organizations[2]][0], teams[organizations[2]][1]]
        # + teams[organizations[3]]
        + teams[organizations[4]]
    )


def default_changeable_teams(teams, organizations):
    return [teams[organizations[1]][0], teams[organizations[2]][1]] + teams[organizations[4]]
