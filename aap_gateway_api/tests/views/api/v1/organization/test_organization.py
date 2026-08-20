from unittest.mock import patch

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry

from aap_gateway_api.models import Organization, Team


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


@pytest.mark.django_db(transaction=True)
class TestOrgDeleteCleansUpRBAC:
    """Verify that a successful org delete removes all RBAC data consistently."""

    @staticmethod
    def _invalidate_permission_registry_ct_cache():
        """Invalidate stale cached_property values on permission_registry.

        transaction=True tests truncate and reload all tables, which can
        reassign ContentType PKs.  permission_registry caches team_ct_id
        and org_ct_id as @cached_property so they survive across tests
        within the same xdist worker, leading to stale lookups in the
        RBAC flush path (AAP-88508).
        """
        for attr in ('team_ct_id', 'org_ct_id'):
            try:
                delattr(permission_registry, attr)
            except AttributeError:
                pass

    def test_successful_delete_cleans_up_everything(self, admin_api_client, organization, team, user):
        self._invalidate_permission_registry_ct_cache()

        RoleDefinition.objects.managed.org_member.give_permission(user, organization)
        RoleDefinition.objects.managed.team_member.give_permission(user, team)

        assert RoleUserAssignment.objects.filter(user_id=user.pk, object_id=organization.pk).exists()
        assert RoleUserAssignment.objects.filter(user_id=user.pk, object_id=team.pk).exists()

        url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})
        response = admin_api_client.delete(url)
        assert response.status_code == 204

        assert not Organization.objects.filter(pk=organization.pk).exists()
        assert not Team.objects.filter(pk=team.pk).exists()
        assert not RoleUserAssignment.objects.filter(object_id=organization.pk).exists()
        assert not RoleUserAssignment.objects.filter(object_id=team.pk).exists()
        assert not ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).exists()


@pytest.mark.django_db(transaction=True)
class TestOrgDeleteRBACFlushRollback:
    """Verify that RBAC flush failure rolls back the entire org delete.

    The call chain is:
      dispatch() -> defer_rbac_computations [with transaction.atomic]
        -> perform_destroy() [@transaction.atomic — savepoint]
          -> instance.delete() -> signals fire, work deferred
        -> defer_rbac_computations.__exit__ -> _flush_rbac()

    If the flush raises, transaction.atomic must roll back the delete
    so the org and all RBAC data remain intact.
    """

    def test_flush_failure_rolls_back_delete(self, admin_api_client, organization, team, user):
        RoleDefinition.objects.managed.org_member.give_permission(user, organization)
        RoleDefinition.objects.managed.team_member.give_permission(user, team)

        org_assignments_before = RoleUserAssignment.objects.filter(object_id=organization.pk).count()
        team_assignments_before = RoleUserAssignment.objects.filter(object_id=team.pk).count()

        url = get_relative_url("organization-detail", kwargs={"pk": organization.pk})

        with (
            patch(
                "ansible_base.rbac.triggers.compute_team_member_roles",
                create=True,
                side_effect=RuntimeError("Simulated RBAC flush failure"),
            ),
            patch(
                "ansible_base.rbac.triggers.compute_object_role_permissions",
                create=True,
                side_effect=RuntimeError("Simulated RBAC flush failure"),
            ),
            patch(
                "ansible_base.rbac.caching.compute_team_member_roles",
                side_effect=RuntimeError("Simulated RBAC flush failure"),
            ),
            patch(
                "ansible_base.rbac.caching.compute_object_role_permissions",
                side_effect=RuntimeError("Simulated RBAC flush failure"),
            ),
        ):
            try:
                response = admin_api_client.delete(url)
                assert response.status_code == 500
            except RuntimeError:
                pass

        assert Organization.objects.filter(pk=organization.pk).exists(), (
            "Organization was deleted despite RBAC flush failure -- the flush is running OUTSIDE the transaction!"
        )

        assert Team.objects.filter(pk=team.pk).exists(), "Team was deleted despite RBAC flush failure -- cascade delete was not rolled back!"

        assert RoleUserAssignment.objects.filter(user_id=user.pk, object_id=organization.pk).count() == org_assignments_before
        assert RoleUserAssignment.objects.filter(user_id=user.pk, object_id=team.pk).count() == team_assignments_before
