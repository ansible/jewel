import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize("view_name", [('user-authorized-tokens-list'), ('user-personal-tokens-list')])
def test_ensure_oauth2_tokens_in_user_view(view_name, system_user):
    get_relative_url(view_name, kwargs={'pk': system_user.pk})


def test_system_user_not_in_user_list_view(admin_api_client, user_api_client, user, admin_user, system_user):
    url = get_relative_url("user-list")
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert response.data['count'] == 2

    for result in response.data['results']:
        assert result['id'] != system_user.pk
