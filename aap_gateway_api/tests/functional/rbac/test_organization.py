import pytest
from django.test import override_settings
from django.urls import reverse

from aap_gateway_api.models import User
from aap_gateway_api.tests.functional.rbac.conftest import api_get_and_assert


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
    organizations[0].add_admin(user)
    organizations[1].add_member(user)
    organizations[2].add_member(user2)
    api_get_and_assert(url, user_api_client, [organizations[0], organizations[1]])

    # User can be in both users and admins with no change
    # Another user doesn't influence result
    organizations[0].add_member(user)
    organizations[0].add_member(user2)
    organizations[1].remove_member(user)
    organizations[1].add_admin(user2)
    api_get_and_assert(url, user_api_client, [organizations[0]])


def test_organization_detail_permissions(user_api_client, user, organization_factory):
    organizations = [organization_factory("Test Org 1"), organization_factory("Test Org 2")]

    urls = [reverse('organization-detail', kwargs={'pk': organizations[0].pk}), reverse('organization-detail', kwargs={'pk': organizations[1].pk})]

    response = user_api_client.get(urls[0])
    assert response.status_code == 404

    organizations[0].add_member(user)
    response = user_api_client.get(urls[0])
    assert response.status_code == 200

    response = user_api_client.get(urls[1])
    assert response.status_code == 404

    organizations[1].add_admin(user)
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
    organizations[0].add_member(user)
    response = user_api_call(urls[0], data={"name": new_name})
    assert response.status_code == 403

    # Can change => 200
    organizations[0].add_admin(user)
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
    organization.add_member(user)
    response = user_api_client.delete(url)
    assert response.status_code == 403

    # User can change => success 204
    organization.add_admin(user)
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

    for assoc_type in ['users', 'admins']:
        url = urls_assoc[assoc_type]

        assert organization.users.count() == 0, assoc_type  # the user themselves
        assert organization.admins.count() == 0, assoc_type
        #
        # No membership
        #  => can't see organization, can't associate
        response = user_api_client.post(url, data={"instances": [user.pk]})
        assert response.status_code == 404, f"Adding self to '{assoc_type}' shouldn't be allowed"
        response = user_api_client.post(url, data={"instances": [user2.pk]})
        assert response.status_code == 404, f"Adding user2 to '{assoc_type}' shouldn't be allowed"
        #
        # User is Org Member
        # => can't associate
        organization.add_member(user)
        response = user_api_client.post(url, data={"instances": [user2.pk]})
        assert response.status_code == 403
        if assoc_type == 'users':
            assert organization.users.count() == 1
            assert organization.users.first() == user
        else:
            assert organization.admins.count() == 0

        # User is Org Admin
        # => Can associate
        organization.remove_member(user)
        organization.add_admin(user)

        assert organization.users.count() == 0, assoc_type
        assert organization.admins.count() == 1, assoc_type
        response = user_api_client.post(url, data={"instances": [user.pk, user2.pk, user3.pk]})
        assert response.status_code == 204
        if assoc_type == 'users':
            assert organization.users.count() == 3
            assert organization.admins.count() == 1
        else:
            assert organization.users.count() == 0
            assert organization.admins.count() == 3

        # Cleanup
        for u in [user, user2, user3]:
            organization.remove_member(u)
            organization.remove_admin(u)


def test_organization_disassociation_permissions(user_api_client, user, user_factory, organization, org_member_rd):
    user2 = user_factory("Test User 2")
    user3 = user_factory("Test User 3")

    urls_disassoc = dict(
        users=reverse("organization-users-disassociate", kwargs={"pk": organization.pk}),
        admins=reverse("organization-admins-disassociate", kwargs={"pk": organization.pk}),
    )
    for assoc_type in ['users', 'admins']:
        url = urls_disassoc[assoc_type]

        organization.add_member(user2)
        organization.add_admin(user3)

        # No permissions, can't see action
        response = user_api_client.post(url, data={"instances": [user.pk, user2.pk, user3.pk]})
        assert response.status_code == 404

        # Org Member, no permissions => forbidden
        organization.add_member(user)
        response = user_api_client.post(url, data={"instances": [user2.pk, user3.pk]})
        assert response.status_code == 403

        # Org Member can't remove self => forbidden
        response = user_api_client.post(url, data={"instances": [user.pk]})
        assert response.status_code == 403

        # Org Admin can remove others => ok
        organization.add_admin(user)
        response = user_api_client.post(url, data={"instances": [user2.pk if assoc_type == 'users' else user3.pk]})
        assert response.status_code == 204
        if assoc_type == 'users':
            assert organization.users.count() == 1  # user (user2 disassociated)
            assert organization.admins.count() == 2  # user + user3
        else:
            assert organization.users.count() == 2  # user + user2
            assert organization.admins.count() == 1  # user (user3 disassociated)

        # Removing non-members ends with Bad Request
        response = user_api_client.post(url, data={"instances": [user3.pk if assoc_type == 'users' else user2.pk]})
        assert response.status_code == 400

        # Org Admin can remove self
        response = user_api_client.post(url, data={"instances": [user.pk]})
        assert response.status_code == 204, response.data
        if assoc_type == 'users':
            assert organization.users.count() == 0  # user disassociated
            assert organization.admins.count() == 2  # user + user3
        else:
            assert organization.users.count() == 2  # user + user2
            assert organization.admins.count() == 0  # user disassociated

        # Cleanup
        for u in [user, user2, user3]:
            organization.remove_member(u)
            organization.remove_admin(u)


@pytest.mark.django_db
class TestOrganizationOptions:
    # @pytest.mark.xfail(reason="Not implemented yet")
    def test_organizations_list_options_user(self, user_api_client, user, organization, org_member_rd, org_admin_rd):
        """Any standard role can't create organization"""
        url = reverse("organization-list")
        roles = [None, org_member_rd, org_admin_rd]
        for role in roles:
            for r in roles:
                if role == r and r is not None:
                    r.give_permission(user, organization)
                elif role != r and r is not None:
                    r.remove_permission(user, organization)

            role_name = role.name if role else 'No Org role'

            response = user_api_client.options(url)
            assert response.status_code == 200
            assert response.data.get('actions', {}).get('POST', None) is None, f"POST action shouldn't be available for {role_name}"

    # @pytest.mark.xfail(reason="Not implemented yet")
    def test_organizations_list_options_platform_auditor(self, user_api_client, user):
        url = reverse("organization-list")
        user.is_platform_auditor = True
        user.save()

        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('POST', None) is None, "POST action shouldn't be available for system auditor"

    def test_organizations_list_options_superuser(self, admin_api_client, user):
        url = reverse("organization-list")

        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('POST', None) is not None, "POST action should be available for superuser"

    def test_organization_detail_options_user(self, user_api_client, user, organization, org_member_rd, org_admin_rd):
        """Any standard role can't change organization"""
        url = reverse("organization-detail", kwargs={"pk": organization.pk})
        roles = [None, org_member_rd, org_admin_rd]
        for role in roles:
            for r in roles:
                if role == r and r is not None:
                    r.give_permission(user, organization)
                elif role != r and r is not None:
                    r.remove_permission(user, organization)

            role_name = role.name if role else 'No Org role'

            response = user_api_client.options(url)
            assert response.status_code == 200

            if role == org_admin_rd:
                assert response.data.get('actions', {}).get('PUT', None) is not None, f"PUT action should be available for {role_name}"
            else:
                assert response.data.get('actions', {}).get('PUT', None) is None, f"PUT action shouldn't be available for {role_name}"

    # @pytest.mark.xfail(reason="Not implemented yet")
    def test_organization_detail_options_platform_auditor(self, user_api_client, user, organization):
        url = reverse("organization-detail", kwargs={"pk": organization.pk})
        user.is_platform_auditor = True
        user.save()

        response = user_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is None, "PUT action shouldn't be available for system auditor"

    def test_organization_detail_options_superuser(self, admin_api_client, user, organization):
        url = reverse("organization-detail", kwargs={"pk": organization.pk})

        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action should be available for superuser"


@override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=False)
@pytest.mark.django_db
@pytest.mark.parametrize("api_type", ["old", "new"])
def test_admin_add_permission(user_api_client, user, org_member_rd, org_admin_rd, organization, api_type):
    other_user = User.objects.create(username='another-user')
    org_admin_rd.give_permission(user, organization)

    if api_type == 'old':
        # Method 1 for adding user as admin of organization - use deprecated association endpoint
        # denied because user can not see other_user
        url = reverse('organization-admins-associate', kwargs={'pk': organization.pk})
        r = user_api_client.post(url, data={'instances': [other_user.id]})
        assert r.status_code == 400
        assert 'does not exist' in str(r.data)
    else:
        # Method 2 for adding user as admin of organization - use DAB RBAC API
        # denied because user can not see other_user
        url = reverse('roleuserassignment-list')
        r = user_api_client.post(url, data={'object_id': organization.pk, 'user': other_user.id, 'role_definition': org_member_rd.id})
        assert r.status_code == 400
        assert 'does not exist' in str(r.data)

    # If user can see other_user, then action can complete successfully
    org_member_rd.give_permission(other_user, organization)

    if api_type == 'old':
        url = reverse('organization-admins-associate', kwargs={'pk': organization.pk})
        r = user_api_client.post(url, data={'instances': [other_user.id]})
        assert r.status_code == 204
    else:
        url = reverse('roleuserassignment-list')
        r = user_api_client.post(url, data={'object_id': organization.pk, 'user': other_user.id, 'role_definition': org_admin_rd.id})
        assert r.status_code == 201
    assert other_user.has_obj_perm(organization, 'change')
