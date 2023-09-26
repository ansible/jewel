import pytest
from django.urls import reverse

from aap_gateway_api.models import HTTPPort


@pytest.mark.django_db(transaction=True)
def test_http_port_api_port_unique_via_api(admin_api_client, http_api_port_factory):
    """
    We can only have one API HTTPPort.
    """

    http_api_port_factory()
    url = reverse('http_port-list')
    data = {
        'name': 'test api port clash',
        'is_api_port': True,
        'number': 1337,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400


def test_http_port_api_port_detail(admin_api_client, http_api_port_factory):
    """
    HTTPPort detail view returns the correct data with an API port.
    """
    http_api_port = http_api_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_api_port.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['number'] == http_api_port.number
    assert response.data['is_api_port'] == http_api_port.is_api_port
    assert response.data['use_https'] == http_api_port.use_https


def test_http_port_regular_port_detail(admin_api_client, http_port_factory):
    """
    HTTPPort detail view returns the correct data with a regular port.
    """
    http_port = http_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_port.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['number'] == http_port.number
    assert response.data['is_api_port'] == http_port.is_api_port
    assert response.data['use_https'] == http_port.use_https


def test_http_port_list(admin_api_client, http_port_factory, http_api_port_factory):
    http_port_1 = http_port_factory()
    http_port_2 = http_port_factory()
    http_api_port = http_api_port_factory()
    url = reverse('http_port-list')
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 3

    for port in enumerate((http_port_1, http_port_2, http_api_port)):
        for attr in ('number', 'is_api_port', 'use_https'):
            assert response.data['results'][port[0]][attr] == getattr(port[1], attr)


def test_http_port_create(admin_api_client):
    url = reverse('http_port-list')
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201
    assert response.data['number'] == data['number']
    assert response.data['is_api_port'] == data['is_api_port']
    assert response.data['use_https'] == data['use_https']
    assert HTTPPort.objects.filter(pk=response.data['id']).exists()


def test_http_port_update(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_port.pk})
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.put(url, data=data)
    assert response.status_code == 200
    assert response.data['number'] == data['number']
    assert response.data['is_api_port'] == data['is_api_port']
    assert response.data['use_https'] == data['use_https']


def test_http_port_update_unauthenticated(unauthenticated_api_client, http_port_factory):
    http_port = http_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_port.pk})
    data = {
        'name': 'test port',
        'number': 1337,
        'is_api_port': False,
        'use_https': True,
    }
    response = unauthenticated_api_client.put(url, data=data)
    assert response.status_code == 401


def test_http_port_update_nonexistent(admin_api_client):
    url = reverse('http_port-detail', kwargs={'pk': 1337})
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
    url = reverse('http_port-detail', kwargs={'pk': http_port.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204


def test_http_port_delete_unauthenticated(unauthenticated_api_client, http_port_factory):
    http_port = http_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_port.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_delete_nonexistent(admin_api_client):
    url = reverse('http_port-detail', kwargs={'pk': 1337})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_http_port_delete_api_port(admin_api_client, http_api_port_factory):
    http_api_port = http_api_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_api_port.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204


def test_http_port_delete_api_port_unauthenticated(unauthenticated_api_client, http_api_port_factory):
    http_api_port = http_api_port_factory()
    url = reverse('http_port-detail', kwargs={'pk': http_api_port.pk})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_delete_api_port_nonexistent(admin_api_client):
    url = reverse('http_port-detail', kwargs={'pk': 1337})
    response = admin_api_client.delete(url)
    assert response.status_code == 404


def test_http_port_delete_api_port_nonexistent_unauthenticated(unauthenticated_api_client):
    url = reverse('http_port-detail', kwargs={'pk': 1337})
    response = unauthenticated_api_client.delete(url)
    assert response.status_code == 401


def test_http_port_number_must_be_unique(admin_api_client, http_port_factory):
    http_port = http_port_factory()
    url = reverse('http_port-list')
    data = {
        'name': 'test port',
        'number': http_port.number,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['number'][0].code == 'unique'


@pytest.mark.parametrize(
    'number, err_substr',
    [
        (0, "greater than or equal to 1"),
        (65536, "less than or equal to 65535"),
        (-1, "greater than or equal to 1"),
    ],
)
def test_http_port_number_must_be_valid_port(admin_api_client, number, err_substr):
    url = reverse('http_port-list')
    data = {
        'name': 'test port',
        'number': number,
        'is_api_port': False,
        'use_https': True,
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert err_substr in response.data['number'][0]
