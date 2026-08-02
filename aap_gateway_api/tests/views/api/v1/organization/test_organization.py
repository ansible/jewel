from unittest.mock import patch

import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.db import IntegrityError

from aap_gateway_api.models import Organization


class TestOrganizationConcurrentCreate:
    """Tests for handling race conditions when SSO/LDAP auto-creates organizations
    concurrently with API creation requests (AAP-25071)."""

    def test_create_returns_existing_org_on_integrity_error(self, admin_api_client):
        """When an org is concurrently created (e.g. by SSO), the API should
        return the existing org with 201 instead of raising an error."""
        # Pre-create the org directly in the DB, simulating SSO auto-creation
        sso_org = Organization.objects.create(name="SSO-Org")

        # Mock perform_create to simulate the race condition:
        # serializer.is_valid() passed (org didn't exist yet), but by the time
        # perform_create runs, the org already exists, causing an IntegrityError.
        with patch(
            'aap_gateway_api.views.api.v1.organization.OrganizationViewSet.perform_create',
            side_effect=IntegrityError('duplicate key value violates unique constraint "aap_gateway_api_organization_name_key"'),
        ):
            url = get_relative_url("organization-list")
            response = admin_api_client.post(url, data={"name": "SSO-Org"})

        assert response.status_code == 201
        assert response.data["name"] == "SSO-Org"
        assert response.data["id"] == sso_org.id

    def test_create_returns_existing_org_preserves_description(self, admin_api_client):
        """The returned org data should reflect the existing org's fields."""
        Organization.objects.create(name="SSO-Org-Desc", description="Created by SSO")

        with patch(
            'aap_gateway_api.views.api.v1.organization.OrganizationViewSet.perform_create',
            side_effect=IntegrityError('duplicate key value violates unique constraint'),
        ):
            url = get_relative_url("organization-list")
            response = admin_api_client.post(url, data={"name": "SSO-Org-Desc"})

        assert response.status_code == 201
        assert response.data["name"] == "SSO-Org-Desc"
        assert response.data["description"] == "Created by SSO"

    def test_integrity_error_without_name_reraises(self, admin_api_client):
        """If the request has no name field, the IntegrityError should propagate
        to the default exception handler."""
        with patch(
            'aap_gateway_api.views.api.v1.organization.OrganizationViewSet.perform_create',
            side_effect=IntegrityError('some other constraint violation'),
        ):
            url = get_relative_url("organization-list")
            # Send a request without 'name' -- the serializer would normally
            # catch this, so we also need to bypass validation.
            with patch(
                'aap_gateway_api.serializers.organization.OrganizationSerializer.is_valid',
                return_value=True,
            ):
                response = admin_api_client.post(url, data={})

        # The gateway_exception_handler converts IntegrityError to a ParseError (400)
        assert response.status_code == 400

    def test_integrity_error_org_not_found_reraises(self, admin_api_client):
        """If IntegrityError occurs but the org can't be found by name,
        the error should propagate."""
        with patch(
            'aap_gateway_api.views.api.v1.organization.OrganizationViewSet.perform_create',
            side_effect=IntegrityError('some constraint violation'),
        ):
            url = get_relative_url("organization-list")
            # Name that doesn't exist -- IntegrityError is from something else
            response = admin_api_client.post(url, data={"name": "nonexistent-org-xyz"})

        # The gateway_exception_handler converts IntegrityError to a ParseError (400)
        assert response.status_code == 400


def test_prevent_deletion_of_managed_organization(admin_api_client):
    org = Organization.objects.create(name="TestOrg", managed=True)
    org.refresh_from_db()
    assert org.managed is True
    url = get_relative_url("organization-detail", kwargs={"pk": org.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 400
    assert response.data["details"] == "Managed organizations cannot be deleted."


def test_organizations_list(admin_api_client, organization):
    Organization.objects.filter(name='Default').delete()
    url = get_relative_url("organization-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == organization.name


@pytest.mark.parametrize(
    "key, route",
    [
        ("users", "organization-users-list"),
        ("admins", "organization-admins-list"),
        ("teams", "organization-teams-list"),
    ],
)
def test_organizations_related_fields(admin_api_client, organization, key, route):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    organization = response.data
    assert key in organization["related"]
    # assure link is a valid URL
    response = admin_api_client.get(organization["related"][key])
    assert response.status_code == 200, response.data


def test_organizations_list_unauthenticated(unauthenticated_api_client):
    url = get_relative_url("organization-list")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


def test_organizations_create(admin_api_client, randname):
    Organization.objects.all().delete()
    url = get_relative_url("organization-list")
    random_name = randname("Test Organization")
    response = admin_api_client.post(url, data={"name": random_name})
    assert response.status_code == 201
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["name"] == random_name


@pytest.mark.parametrize(
    "description",
    [
        "A test organization, which is thusly described.",
        "",
        None,
    ],
)
def test_organizations_create_description_is_optional(admin_api_client, randname, description):
    Organization.objects.all().delete()
    url = get_relative_url("organization-list")
    random_name = randname("Test Organization")
    data = {"name": random_name}
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


def test_organizations_create_unauthenticated(unauthenticated_api_client, randname):
    url = get_relative_url("organization-list")
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.post(url, data={"name": random_name})
    assert response.status_code == 401
    assert Organization.objects.filter(name=random_name).count() == 0


def test_organizations_update(admin_api_client, organization, randname):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    random_name = randname("Test Organization")
    response = admin_api_client.put(url, data={"name": random_name})
    assert response.status_code == 200
    assert response.data["name"] == random_name

    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == random_name


def test_organizations_update_unauthenticated(unauthenticated_api_client, organization, randname):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    random_name = randname("Test Organization")
    response = unauthenticated_api_client.put(url, data={"name": random_name})
    assert response.status_code == 401


def test_organizations_delete(admin_api_client, organization):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204

    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_organizations_delete_unauthenticated(unauthenticated_api_client, organization):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_organizations_delete_nonexistent(admin_api_client):
    url = get_relative_url("organization-detail", kwargs={"pk": 999})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_organizations_users_associate(admin_api_client, organization, user):
    """
    Test that we can associate users with an organization.
    """
    url = get_relative_url("organization-users-associate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.users.count() == 1
    assert user in organization.users.all()


def test_organizations_summary_fields_counts(admin_api_client, organization, organization_1, user, team, team_1):
    url = get_relative_url("organization-detail", kwargs={"pk": organization_1.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["related_field_counts"]["users"] == 0
    assert response.data["summary_fields"]["related_field_counts"]["teams"] == 0

    organization_1.add_member(user)
    organization_1.teams.add(team, team_1)
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["related_field_counts"]["users"] == 1
    assert response.data["summary_fields"]["related_field_counts"]["teams"] == 2


def test_organizations_admins_association(admin_api_client, organization, user):
    """
    Test that we can (dis)associate admins with an organization (from the org side).
    """
    assert organization.admins.count() == 0

    url = get_relative_url("organization-admins-associate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.admins.count() == 1
    assert organization.admins.first() == user

    url = get_relative_url("organization-admins-disassociate", kwargs={"pk": organization.pk})
    response = admin_api_client.post(url, data={"instances": [user.pk]})
    assert response.status_code == 204
    assert organization.admins.count() == 0


def test_organizations_resource_summary_fields(admin_api_client, organization):
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["summary_fields"]["resource"]["ansible_id"] == organization.resource.ansible_id
    assert response.data["summary_fields"]["resource"]["resource_type"] == organization.resource.resource_type


def test_managed_organization_field_API(admin_api_client, organization):
    """Test to ensure organization managed cannot be set to true via the API."""
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert organization.managed is False
    response = admin_api_client.patch(url, data={"managed": True})
    assert response.status_code == 200
    assert response.data["managed"] is False


def test_managed_organization_field_manual(admin_api_client):
    """Test to ensure that it can be set to true via command line"""
    organization = Organization.objects.create(name="testing", managed=True)
    url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
    response = admin_api_client.get(url)
    assert organization.managed is True
    response = admin_api_client.patch(url, data={"managed": False})
    assert response.status_code == 200
    assert response.data["managed"] is True
