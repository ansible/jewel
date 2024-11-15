from unittest import mock

import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import HTTPPort


@pytest.mark.django_db(transaction=True)
def test_http_port_api_port_unique_via_api(admin_api_client, http_api_port_factory):
    """
    We can only have one API HTTPPort.
    """

    http_api_port_factory()
    url = get_relative_url('http_port-list')
    data = {
        'name': 'test api port clash',
        'is_api_port': True,
        'number': 1337,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400


def test_http_port_api_port_cannot_be_deleted(admin_api_client, http_api_port_factory):
    """
    We can not delete the API port (via proxy or otherwise).
    """

    port = http_api_port_factory()
    assert port.is_api_port
    url = get_relative_url('http_port-detail', kwargs={'pk': port.pk})
    # Via proxy, we hit the block on all dangerous operations
    with mock.patch('aap_gateway_api.utils.views.permissions.from_proxy', return_value=True):
        response = admin_api_client.delete(url)
        assert response.status_code == 403
    # Direct, we fallback to the view blocking this operation.
    response = admin_api_client.delete(url)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    'factory, success_expected',
    [
        ('http_port_factory', False),
        ('http_api_port_factory', True),
    ],
)
def test_service_api_route_validate_http_port(request, full_service_hierarchy_controller, admin_api_client, factory, success_expected):
    url = get_relative_url('service-list')
    fixture = request.getfixturevalue(factory)
    port = fixture()
    data = {
        'name': 'test service',
        'api_slug': 'test-service',
        'service_cluster': full_service_hierarchy_controller.service_cluster.pk,
        'service_port': 31337,
        'service_path': '/test',
        'gateway_path': '/test',
        'http_port': port.pk,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == (201 if success_expected else 400)
    if not success_expected:
        assert 'API HTTP port must be used' in response.data['http_port'][0]


def test_http_port_api_port_cannot_become_regular_port(admin_api_client, http_api_port_factory):
    """
    We can not change the API port to a regular port.
    """

    port = http_api_port_factory()
    assert port.is_api_port
    url = get_relative_url('http_port-detail', kwargs={'pk': port.pk})
    response = admin_api_client.patch(url, data={'is_api_port': False})
    assert response.status_code == 400
    assert "changed to a non-API port" in response.data['is_api_port'][0]


def test_http_port_api_port_detail(admin_api_client, http_api_port_factory):
    """
    HTTPPort detail view returns the correct data with an API port.
    """
    http_api_port = http_api_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_api_port.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['name'] == http_api_port.name
    assert response.data['number'] == http_api_port.number
    assert response.data['is_api_port'] == http_api_port.is_api_port
    assert response.data['use_https'] == http_api_port.use_https


def test_http_port_regular_port_detail(admin_api_client, http_port_factory):
    """
    HTTPPort detail view returns the correct data with a regular port.
    """
    http_port = http_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_port.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['name'] == http_port.name
    assert response.data['number'] == http_port.number
    assert response.data['is_api_port'] == http_port.is_api_port
    assert response.data['use_https'] == http_port.use_https


def test_http_port_list(admin_api_client, http_port_factory, http_api_port_factory):
    http_port_1 = http_port_factory()
    http_port_2 = http_port_factory()
    http_api_port = http_api_port_factory()
    url = get_relative_url('http_port-list')
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 3

    for port in enumerate((http_port_1, http_port_2, http_api_port)):
        for attr in ('name', 'number', 'is_api_port', 'use_https'):
            assert response.data['results'][port[0]][attr] == getattr(port[1], attr)


def test_http_port_create(admin_api_client):
    url = get_relative_url('http_port-list')
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert response.data['name'] == data['name']
    assert response.data['number'] == data['number']
    assert response.data['is_api_port'] == data['is_api_port']
    assert response.data['use_https'] == data['use_https']
    assert HTTPPort.objects.filter(pk=response.data['id']).exists()


def test_http_port_update(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_port.pk})
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.put(url, data=data)
    assert response.status_code == 200
    assert response.data['name'] == data['name']
    assert response.data['number'] == data['number']
    assert response.data['is_api_port'] == data['is_api_port']
    assert response.data['use_https'] == data['use_https']


def test_http_port_update_unauthenticated(unauthenticated_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_port.pk})
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = unauthenticated_api_client.put(url, data=data)
    assert response.status_code == 401


def test_http_port_update_nonexistent(admin_api_client):
    url = get_relative_url('http_port-detail', kwargs={'pk': 1337})
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.put(url, data=data)
    assert response.status_code == 404


def test_http_port_delete(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_port.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204


def test_http_port_delete_unauthenticated(unauthenticated_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_port.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_delete_nonexistent(admin_api_client):
    url = get_relative_url('http_port-detail', kwargs={'pk': 1337})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_http_port_delete_api_port_unauthenticated(unauthenticated_api_client, http_api_port_factory):
    http_api_port = http_api_port_factory()
    url = get_relative_url('http_port-detail', kwargs={'pk': http_api_port.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_delete_api_port_nonexistent(admin_api_client):
    url = get_relative_url('http_port-detail', kwargs={'pk': 1337})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_http_port_delete_api_port_nonexistent_unauthenticated(unauthenticated_api_client):
    url = get_relative_url('http_port-detail', kwargs={'pk': 1337})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_number_must_be_unique(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-list')
    data = {
        'name': 'test port',
        'number': http_port.number,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['number'][0].code == 'unique'


def test_http_port_name_must_be_unique(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = get_relative_url('http_port-list')
    data = {
        'name': http_port.name,
        'number': 1357,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['name'][0].code == 'unique'


@pytest.mark.parametrize(
    'number, err_substr',
    [
        (0, "greater than or equal to 1"),
        (65536, "less than or equal to 65535"),
        (-1, "greater than or equal to 1"),
    ],
)
def test_http_port_number_must_be_valid_port(admin_api_client, number, err_substr):
    url = get_relative_url('http_port-list')
    data = {
        'name': 'test port',
        'number': number,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert err_substr in response.data['number'][0]
