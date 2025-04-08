import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
class TestUserOrganizationsAssociations:
    @pytest.mark.parametrize(
        "user_type",
        ["is_superuser", "is_platform_auditor", "is_normal_user"],
    )
    @pytest.mark.parametrize(
        "association_type",
        ["organization-users-associate", "organization-admins-associate"],
    )
    def test_user_organizations_associations(self, admin_api_client, organization_factory, user_type, association_type):
        # Create an Admin user: test_user1
        users_url = get_relative_url("user-list")
        data = {"username": "test_user1", "password": "test_password1", "is_superuser": True}
        user1_response = admin_api_client.post(users_url, data=data, format='json')

        assert user1_response.status_code == 201
        assert user1_response.data['username'] == data['username']

        # Add 3 Organizations as associations for this user
        organizations = [organization_factory("Test Org 1"), organization_factory("Test Org 2"), organization_factory("Test Org 3")]

        org_assoc_url0 = get_relative_url(association_type, kwargs={"pk": organizations[0].pk})
        response_user1_org_assoc0 = admin_api_client.post(org_assoc_url0, data={"instances": [user1_response.data['id']]})
        assert response_user1_org_assoc0.status_code == 204

        org_assoc_url1 = get_relative_url(association_type, kwargs={"pk": organizations[1].pk})
        response_user1_org_assoc1 = admin_api_client.post(org_assoc_url1, data={"instances": [user1_response.data['id']]})
        assert response_user1_org_assoc1.status_code == 204

        org_assoc_url2 = get_relative_url(association_type, kwargs={"pk": organizations[2].pk})
        response_user1_org_assoc2 = admin_api_client.post(org_assoc_url2, data={"instances": [user1_response.data['id']]})
        assert response_user1_org_assoc2.status_code == 204

        # Create a second user: test_user2 based on the passed user_type
        data = {"username": "test_user2", "password": "test_password2"}
        if user_type == 'is_superuser':
            data["is_superuser"] = True
        elif user_type == 'is_platform_auditor':
            data["is_platform_auditor"] = True
        elif user_type == 'is_normal_user':
            data["is_superuser"] = False
            data["is_platform_auditor"] = False

        user2_response = admin_api_client.post(users_url, data=data, format='json')

        assert user2_response.status_code == 201
        assert user2_response.data['username'] == data['username']

        # Add ONLY 1 Organization as association for this user
        response_user2_org_assoc0 = admin_api_client.post(org_assoc_url0, data={"instances": [user2_response.data['id']]})
        assert response_user2_org_assoc0.status_code == 204

        # Verify that the associated Orgs for the user: test_user1 returns 3 Orgs
        user1_detail_url = get_relative_url('user-detail', kwargs={'pk': user1_response.data['id']})
        associated_orgs_user1_url = user1_detail_url + 'organizations/'
        associated_user1_org_url_response = admin_api_client.get(associated_orgs_user1_url)

        assert associated_user1_org_url_response.status_code == 200
        assert associated_user1_org_url_response.data['count'] == 3

        org_names = set()
        for result in associated_user1_org_url_response.data['results']:
            org_names.add(result['name'])
        assert set(["Test Org 1", "Test Org 2", "Test Org 3"]) == set(org_names)

        # Verify that the associated Orgs for the user: test_user2 returns ONLY 1 Org
        user2_detail_url = get_relative_url('user-detail', kwargs={'pk': user2_response.data['id']})
        associated_orgs_user2_url = user2_detail_url + 'organizations/'
        associated_user2_org_url_response = admin_api_client.get(associated_orgs_user2_url)

        assert associated_user2_org_url_response.status_code == 200
        assert associated_user2_org_url_response.data['count'] == 1
        assert associated_user2_org_url_response.data['results'][0]['name'] == "Test Org 1"
