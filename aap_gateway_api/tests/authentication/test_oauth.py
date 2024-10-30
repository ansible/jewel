import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize(
    'scope, post_status, patch_status, get_status, delete_status',
    [
        ('write', 201, 200, 200, 204),
        ('read write', 201, 200, 200, 204),
        ('write read', 201, 200, 200, 204),
        ('read', 403, 403, 200, 403),
    ],
)
def test_oauth_pat_scope_adherence(
    unauthenticated_api_client, oauth2_admin_access_token, organization, scope, post_status, patch_status, delete_status, get_status
):
    oauth2_admin_access_token.scope = scope
    oauth2_admin_access_token.save()

    client = unauthenticated_api_client

    url = get_relative_url("organization-list")
    response = client.post(
        url,
        data={"name": "test_oauth_pat_scope_adherence"},
        HTTP_AUTHORIZATION=f"Bearer {oauth2_admin_access_token.token}",
    )
    assert response.status_code == post_status, response.data

    url = get_relative_url("organization-detail", args=[organization.id])
    response = client.patch(
        url,
        data={"name": "another name"},
        HTTP_AUTHORIZATION=f"Bearer {oauth2_admin_access_token.token}",
    )
    assert response.status_code == patch_status, response.data

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {oauth2_admin_access_token.token}",
    )
    assert response.status_code == get_status, response.data

    response = client.delete(
        url,
        HTTP_AUTHORIZATION=f"Bearer {oauth2_admin_access_token.token}",
    )
    assert response.status_code == delete_status, response.data
