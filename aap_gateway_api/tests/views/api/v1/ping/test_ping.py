from unittest import mock

import pytest
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_GOOD
from ansible_base.lib.utils.response import get_relative_url
from django.db import DatabaseError

from aap_gateway_api.models import HTTPPort, ServiceAPIRoute
from aap_gateway_api.version import get_aap_version


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", return_value=True)
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_all_up(request, mock_dispatcherd, unauthenticated_api_client):
    request.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert "pong" in response.data
    assert response.data["pong"] is not None

    assert response.data["version"] == get_aap_version()
    assert response.data['status'] == STATUS_GOOD, response.data
    assert response.data['dispatcherd_connected'] is True


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", return_value=True)
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_db_down(request, mock_dispatcherd, unauthenticated_api_client):
    request.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

    with mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_db", side_effect=DatabaseError):
        url = get_relative_url("ping-view")
        response = unauthenticated_api_client.get(url)
        assert response.status_code == 200
        assert response.data['status'] == STATUS_DEGRADED
        assert response.data['db_exception'] == "DatabaseError"


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", return_value=True)
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_proxy_exception(request, mock_dispatcherd, unauthenticated_api_client, service_cluster_gateway):
    request.side_effect = Exception('testing')

    HTTPPort(name="api", number=9080, is_api_port=True).save()
    ServiceAPIRoute(
        api_slug='gateway',
        service_port=8000,
        is_service_https=True,
        service_cluster=service_cluster_gateway,
    ).save()

    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert response.data['status'] == STATUS_DEGRADED
    assert response.data['proxy_exception_type'] == 'Exception'


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", return_value=True)
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_proxy_non_200(request, mock_dispatcherd, unauthenticated_api_client, service_cluster_gateway):
    request.return_value = mock.Mock(status_code=500, json=lambda: {"test": "test"})

    HTTPPort(name="api", number=9080, is_api_port=True).save()
    ServiceAPIRoute(
        api_slug='gateway',
        service_port=8000,
        is_service_https=True,
        service_cluster=service_cluster_gateway,
    ).save()

    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert response.data['status'] == STATUS_DEGRADED
    assert response.data['proxy_status_code'] == 500


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", return_value=False)
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_dispatcherd_not_running(request, mock_dispatcherd, unauthenticated_api_client):
    """Dispatcherd not running (empty alive reply) must not degrade overall status."""
    request.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert response.data['dispatcherd_connected'] is False
    assert response.data['status'] == STATUS_GOOD


@pytest.mark.django_db
@mock.patch("aap_gateway_api.views.api.v1.ping.PingView._check_dispatcherd", side_effect=Exception("connection refused"))
@mock.patch("aap_gateway_api.views.api.v1.ping.requests.request")
def test_ping_dispatcherd_exception(request, mock_dispatcherd, unauthenticated_api_client):
    """Dispatcherd error must not degrade overall status (informational only)."""
    request.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

    url = get_relative_url("ping-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200
    assert response.data['dispatcherd_connected'] is False
    assert response.data['status'] == STATUS_GOOD
