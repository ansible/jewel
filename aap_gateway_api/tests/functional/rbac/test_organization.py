import pytest
from django.test import override_settings
from django.urls import reverse

from aap_gateway_api.models import User
from aap_gateway_api.tests.functional.rbac.permissions_helper import api_get_and_assert


def test_organization_list_permissions(user_api_client, user, user_factory, organization_factory):
    """
    Reading list of organizations
    - Superuser
    - Admin or User of Org
    """
    organizations = [organization_factory("Test Org 1"), organization_factory("Test Org 2"), organization_factory("Test Org 3")]

    user2 = user_factory("Test User 2")

    url = reverse("organization-list")

    # User sees nothing by default
    api_get_and_assert(url, user_api_client, [])

    # User sees org as either user or admin
    organizations[0].admins.add(user)
    organizations[1].users.add(user)
    organizations[2].users.add(user2)
    api_get_and_assert(url, user_api_client, [organizations[0], organizations[1]])

    # User can be in both users and admins with no change
    # Another user doesn't influence result
    organizations[0].users.add(user)
    organizations[0].users.add(user2)
    organizations[1].users.remove(user)
    organizations[1].admins.add(user2)
    api_get_and_assert(url, user_api_client, [organizations[0]])


def test_organization_detail_permissions(user_api_client, user, organization_factory):
    organizations = [organization_factory("Test Org 1"), organization_factory("Test Org 2")]

    urls = [reverse('organization-detail', kwargs={'pk': organizations[0].pk}), reverse('organization-detail', kwargs={'pk': organizations[1].pk})]

    response = user_api_client.get(urls[0])
    assert response.status_code == 404

    organizations[0].users.add(user)
    response = user_api_client.get(urls[0])
    assert response.status_code == 200

    response = user_api_client.get(urls[1])
    assert response.status_code == 404

    organizations[1].admins.add(user)
    response = user_api_client.get(urls[1])
    assert response.status_code == 200


def test_organization_create_permissions(user_api_client, user, randname):
    url = reverse("organization-list")
    response = user_api_client.post(url, data={"name": randname("Test Organization")})
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["put", "patch"])
def test_organization_update_permissions(user_api_client, user, organization_factory, randname, method):
    organizations = [organization_factory("Test Org 1"), organization_factory("Test Org 2")]

    urls = [reverse('organization-detail', kwargs={'pk': organizations[0].pk}), reverse('organization-detail', kwargs={'pk': organizations[1].pk})]

    user_api_call = getattr(user_api_client, method)
    new_name = randname("Test Organization")

    # Can't view => 404
    response = user_api_call(urls[0], data={"name": new_name})
    assert response.status_code == 404

    # Can view, can't change => 403
    organizations[0].users.add(user)
    response = user_api_call(urls[0], data={"name": new_name})
    assert response.status_code == 403

    # Can change => 200
    organizations[0].admins.add(user)
    response = user_api_call(urls[0], data={"name": new_name})
    assert response.status_code == 200
    assert response.data["name"] == new_name

    # Other Organization access not influenced
    response = user_api_call(urls[1], data={"name": new_name})
    assert response.status_code == 404


def test_organization_delete_permissions(admin_api_client, user_api_client, user, organization):
    url = reverse("organization-detail", kwargs={"pk": organization.pk})

    # User can't see => 404
    response = user_api_client.delete(url)
    assert response.status_code == 404

    # User can see only => 403
    organization.users.add(user)
    response = user_api_client.delete(url)
    assert response.status_code == 403

    # User can change => success 204
    organization.admins.add(user)
    response = user_api_client.delete(url)
    assert response.status_code == 204

    # Check it's really deleted
    response = admin_api_client.get(url)
    assert response.status_code == 404


def test_organization_association_permissions(user_api_client, user, user_factory, organization, org_member_rd):
    user2 = user_factory("Test User 2")
    user3 = user_factory("Test User 3")

    urls_assoc = dict(
        users=reverse("organization-users-associate", kwargs={"pk": organization.pk}),
        admins=reverse("organization-admins-associate", kwargs={"pk": organization.pk}),
    )

    urls_disassoc = dict(
        users=reverse("organization-users-disassociate", kwargs={"pk": organization.pk}),
        admins=reverse("organization-admins-disassociate", kwargs={"pk": organization.pk}),
    )

    org_member_rd.give_permission(user, organization)

    for assoc_type in ['users', 'admins']:
        #
        #   Associations
        #
        url = urls_assoc[assoc_type]

        assert organization.users.count() == 1  # the user themselves
        assert organization.admins.count() == 0

        # No membership, no permissions
        response = user_api_client.post(url, data={"instances": [user.pk]})
        assert (
            response.status_code == 403
        ), f"Adding self to '{assoc_type}' shouldn't be allowed"  # TODO: Should be 404 -> This way user can check that parent org exists
        response = user_api_client.post(url, data={"instances": [user2.pk]})
        assert (
            response.status_code == 403
        ), f"Adding user2 to '{assoc_type}' shouldn't be allowed"  # TODO: Should be 404 -> This way user can check that parent org exists

        # User membership, no permissions
        organization.users.add(user)
        response = user_api_client.post(url, data={"instances": [user2.pk]})
        assert response.status_code == 403
        if assoc_type == 'users':
            assert organization.users.count() == 1
            assert organization.users.first() == user
        else:
            assert organization.admins.count() == 0

        # Admin membership, association allowed
        organization.users.remove(user)
        organization.admins.add(user)

        assert organization.users.count() == 0
        assert organization.admins.count() == 1
        response = user_api_client.post(url, data={"instances": [user.pk, user2.pk, user3.pk]})
        assert response.status_code == 204
        if assoc_type == 'users':
            assert organization.users.count() == 3
            assert organization.admins.count() == 1
        else:
            assert organization.users.count() == 0
            assert organization.admins.count() == 3

        #
        #   Disassociations
        #
        url = urls_disassoc[assoc_type]

        # No permissions, forbidden action
        organization.admins.remove(user)
        response = user_api_client.post(url, data={"instances": [user.pk, user2.pk, user3.pk]})
        assert response.status_code in (403, 404)  # TODO: Should be 404 -> This way user can check that parent org exists

        # Admin can remove others
        organization.admins.add(user)
        response = user_api_client.post(url, data={"instances": [user2.pk, user3.pk]})
        assert response.status_code == 204
        if assoc_type == 'users':
            assert organization.users.count() == 1
        else:
            assert organization.users.count() == 0
        assert organization.admins.count() == 1

        # Admin member can remove self
        response = user_api_client.post(url, data={"instances": [user.pk]})
        assert response.status_code == 204, response.data
        assert organization.users.count() == 0
        if assoc_type == 'users':
            assert organization.admins.count() == 1
            organization.admins.remove(user)
        else:
            assert organization.admins.count() == 0

        # There are no permissions now
        org_member_rd.give_permission(user, organization)  # add as member, for 403 and not 404
        response = user_api_client.post(url, data={"instances": [user2.pk]})
        assert response.status_code == 403


@override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=False)
@pytest.mark.django_db
def test_admin_add_permission(user_api_client, user, org_member_rd, org_admin_rd, organization):
    other_user = User.objects.create(username='another-user')

    org_admin_rd.give_permission(user, organization)
    url = reverse('organization-admins-associate', kwargs={'pk': organization.pk})
    r = user_api_client.post(url, data={'instances': [other_user.id]})
    assert r.status_code == 400
    assert 'does not exist' in str(r.data)

    url = reverse('organization-detail', kwargs={'pk': organization.pk})
    r = user_api_client.patch(url, data={'admins': [other_user.id]})
    assert r.status_code == 400
    assert 'does not exist' in str(r.data)

    # If user can see other_user, then action can complete successfully
    org_member_rd.give_permission(other_user, organization)
    r = user_api_client.patch(url, data={'admins': [other_user.id]})
    assert r.status_code == 200
    assert other_user.has_obj_perm(organization, 'change')
