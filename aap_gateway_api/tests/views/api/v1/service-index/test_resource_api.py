import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import Organization, Team, User


@pytest.mark.parametrize(
    "resource_type, model, nonunique_field, unique_field",
    [
        ("shared.organization", Organization, "description", "name"),
        ("shared.team", Team, "description", "name"),
        ("shared.user", User, "first_name", "username"),
    ],
)
def test_resource_processor_save_with_existing_object(admin_api_client, organization, resource_type, model, nonunique_field, unique_field):
    """We should not error if POSTing an object that exists already."""

    count = model.objects.count()
    resource_data = {unique_field: "my_name"}
    if model is Team:
        resource_data["organization"] = organization.resource.ansible_id

    # Test creating a resource
    url = get_relative_url("resource-list")
    resp = admin_api_client.post(url, {"resource_type": resource_type, "resource_data": resource_data}, format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["resource_data"][unique_field] == "my_name"
    assert model.objects.filter(**{unique_field: "my_name"}).exists()
    assert model.objects.count() == count + 1

    # Do it again - we should not error nor create a new object
    resp = admin_api_client.post(url, {"resource_type": resource_type, "resource_data": resource_data}, format="json")
    assert resp.status_code == 201
    assert resp.data["resource_data"][unique_field] == "my_name"
    assert model.objects.filter(**{unique_field: "my_name"}).exists()
    assert model.objects.count() == count + 1

    # Do it again with mismatched, non-unique fields - we should not error, and we should update the object
    resource_data[nonunique_field] = "my_description"
    resp = admin_api_client.post(url, {"resource_type": resource_type, "resource_data": resource_data}, format="json")
    assert resp.status_code == 201
    assert resp.data["resource_data"][unique_field] == "my_name"
    assert resp.data["resource_data"][nonunique_field] == "my_description"
    assert model.objects.filter(**{unique_field: "my_name"}).exists()
    assert getattr(model.objects.get(**{unique_field: "my_name"}), nonunique_field) == "my_description"
    assert model.objects.count() == count + 1


def test_resource_processor_save_update(admin_api_client):
    """We can PUT/PATCH an object that exists already."""

    count = Organization.objects.count()

    # Test creating an organization
    url = get_relative_url("resource-list")
    resp = admin_api_client.post(url, {"resource_type": "shared.organization", "resource_data": {"name": "my_name"}}, format="json")
    assert resp.status_code == 201
    assert resp.data["name"] == "my_name"
    assert Organization.objects.filter(name="my_name").exists()
    assert Organization.objects.count() == count + 1
    ansible_id = resp.data["ansible_id"]

    # Test updating the organization
    url = get_relative_url("resource-detail", kwargs={"ansible_id": ansible_id})
    resp = admin_api_client.patch(url, {"resource_data": {"description": "my_description"}}, format="json")

    assert resp.status_code == 200
    assert resp.data["resource_data"]["description"] == "my_description"
    assert Organization.objects.get(name="my_name").description == "my_description"
    assert Organization.objects.count() == count + 1
    assert str(Organization.objects.get(name="my_name").resource.ansible_id) == ansible_id
