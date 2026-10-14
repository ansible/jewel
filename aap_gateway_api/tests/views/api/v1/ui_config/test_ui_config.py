import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize('disabled', [True, False])
@pytest.mark.parametrize('client_fixture', ['user_api_client', 'admin_api_client'])
def test_ui_config_returns_pat_creation_setting(request, client_fixture, disabled, preference_manager):
    client = request.getfixturevalue(client_fixture)
    with preference_manager.set('oauth2_provider', 'allow_local_pat_creation', disabled):
        response = client.get(get_relative_url('ui-config-view'))

    assert response.status_code == 200
    assert response.json() == {'personal_access_tokens_allowed': disabled}


def test_ui_config_requires_authentication(unauthenticated_api_client):
    response = unauthenticated_api_client.get(get_relative_url('ui-config-view'))

    assert response.status_code == 401
