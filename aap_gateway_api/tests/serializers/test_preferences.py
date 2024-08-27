import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.test import override_settings


@override_settings(AOC_UNCHANGEABLE_PREFERENCES=['gateway_token_name'])
@pytest.mark.parametrize(
    "is_cloud_install",
    [
        (True),
        (False),
    ],
)
def test_process_fields_aoc_read_only_options_page(is_cloud_install, admin_api_client):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=is_cloud_install):
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
        response = admin_api_client.options(url)
        assert response.status_code == 200
        assert 'actions' in response.data
        assert 'PUT' in response.data['actions']
        assert 'gateway_token_name' in response.data['actions']['PUT']
        assert 'read_only' in response.data['actions']['PUT']['gateway_token_name']
        assert response.data['actions']['PUT']['gateway_token_name']['read_only'] is is_cloud_install


@override_settings(AOC_UNCHANGEABLE_PREFERENCES=['gateway_token_name'])
@pytest.mark.parametrize(
    "is_cloud_install,expected_response_code",
    [
        (True, 400),
        (False, 200),
    ],
)
def test_process_fields_aoc_change_read_only_setting(is_cloud_install, expected_response_code, admin_api_client):
    with override_settings(ANSIBLE_BASE_MANAGED_CLOUD_INSTALL=is_cloud_install):
        url = get_relative_url('setting-section-list', kwargs={'category_slug': 'all'})
        response = admin_api_client.put(url, {'gateway_token_name': 'testing'})
        assert response.status_code == expected_response_code
        if is_cloud_install:
            assert 'gateway_token_name' in response.data
            assert response.data['gateway_token_name'] == 'Cannot be changed in AoC environment'
