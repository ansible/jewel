import time
from typing import List
from unittest import mock

import pytest
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.utils.response import get_relative_url
from django.test import override_settings

from aap_gateway_api.models import HTTPPort, Route, ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.views.api.v1.status import check_console

_REDIS_GOOD = {'mode': 'testing', 'status': STATUS_GOOD}
_REDIS_FAILED = {'mode': 'testing', 'status': STATUS_FAILED}
_REDIS_DEGRADED = {'mode': 'testing', 'status': STATUS_DEGRADED}


def test_status_unauthenticated(unauthenticated_api_client):
    """
    When not authenticated, the status endpoint should not be accessible.
    """
    url = get_relative_url("status-view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 401


def test_status_nonadmin(user_api_client):
    """
    The user must be an admin to access the status endpoint.
    """
    url = get_relative_url("status-view")
    response = user_api_client.get(url)
    assert response.status_code == 403


def test_status_no_services(admin_api_client):
    """
    The status endpoint should return a 200 response.

    By default there are no services, so the status should be "good" and
    there should be no services listed except for redis.
    """
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        # Remove redis from services
        redis = get_service_by_name(response.data, "redis")
        response.data["services"].remove(redis)
        assert response.data["services"] == []


@pytest.mark.parametrize(
    "redis_status",
    [
        (_REDIS_GOOD),
        (_REDIS_FAILED),
        (_REDIS_DEGRADED),
    ],
)
def test_redis_status_changes_overall_status(redis_status, admin_api_client):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=redis_status):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == redis_status['status']


def test_status_route_with_no_nodes(admin_api_client, additional_route_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        # The status ends up being good because the redis is good
        assert response.data["status"] == STATUS_GOOD
        controller = get_service_by_name(response.data, "controller")
        assert controller is None


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_500(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.return_value = mock.Mock(status_code=500, text="test")
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_FAILED
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['nodes'][node_id]["status"] == STATUS_FAILED
        assert controller['nodes'][node_id]["response_code"] == 500
        assert controller['nodes'][node_id]["body"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_200(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.return_value = mock.Mock(status_code=200, json=lambda: {"version": "test"})
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['nodes'][node_id]["status"] == STATUS_GOOD
        assert controller['nodes'][node_id]["response"] == {"version": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_exception(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.side_effect = Exception("test")
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_FAILED
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['nodes'][node_id]["status"] == STATUS_FAILED
        assert controller['nodes'][node_id]["exception"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_routes_same_service_cluster(get, admin_api_client, full_service_hierarchy_controller, http_port_factory, randname):
    """
    Test that the status endpoint can handle multiple routes to the same service cluster.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"version": "test"})

    port = http_port_factory()
    route_copy = full_service_hierarchy_controller.route
    route_copy.pk = None
    route_copy.id = None
    route_copy.http_port = port
    route_copy.name = randname('Different Route')
    route_copy.save()

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['nodes'][node_id]["status"] == STATUS_GOOD
        assert controller['nodes'][node_id]["response"] == {"version": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_multiple_service_nodes(get, admin_api_client, full_service_hierarchy_controller):
    """
    Test that the status endpoint can handle multiple service nodes pointing to the same service cluster.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"version": "test"})

    new_service_node = ServiceNode.objects.create(
        name="Node 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )
    another_service_node = ServiceNode.objects.create(
        name="Node 127.0.0.100",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.100",
    )

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None

        assert len(controller['nodes']) == 3

        assert controller['status'] == STATUS_GOOD

        node_id_1 = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        node_id_2 = f"{new_service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        node_id_3 = f"{another_service_node.address}:{full_service_hierarchy_controller.route.service_port}"

        for node_id in (node_id_1, node_id_2, node_id_3):
            assert controller['nodes'][node_id]["status"] == STATUS_GOOD
            assert controller['nodes'][node_id]["response"] == {"version": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_hierarchies(get, admin_api_client, full_service_hierarchy_controller, full_service_hierarchy_hub):
    """
    Test that the status endpoint can handle multiple complete service hierarchies.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"version": "test"})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        hub = get_service_by_name(response.data, "hub")
        assert hub is not None

        node_id_controller = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['status'] == STATUS_GOOD
        assert controller['nodes'][node_id_controller]["status"] == STATUS_GOOD
        assert controller['nodes'][node_id_controller]["response"] == {"version": "test"}

        node_id_hub = f"{full_service_hierarchy_hub.service_node.address}:{full_service_hierarchy_hub.route.service_port}"
        assert hub['status'] == STATUS_GOOD
        assert hub['nodes'][node_id_hub]["status"] == STATUS_GOOD
        assert hub['nodes'][node_id_hub]["response"] == {"version": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_hierarchies_services_formatted_with_keys_via_query_param(
    get, admin_api_client, full_service_hierarchy_controller, full_service_hierarchy_hub
):
    """
    Test that the status endpoint can handle multiple complete service hierarchies.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"version": "test"})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url, data={"service_keys": "True"})

        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        controller = response.data["services"]["controller"]
        assert controller is not None
        hub = response.data["services"]["hub"]
        assert hub is not None

        node_id_controller = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert controller['status'] == STATUS_GOOD
        assert controller['nodes'][node_id_controller]["status"] == STATUS_GOOD
        assert controller['nodes'][node_id_controller]["response"] == {"version": "test"}

        node_id_hub = f"{full_service_hierarchy_hub.service_node.address}:{full_service_hierarchy_hub.route.service_port}"
        assert hub['status'] == STATUS_GOOD
        assert hub['nodes'][node_id_hub]["status"] == STATUS_GOOD
        assert hub['nodes'][node_id_hub]["response"] == {"version": "test"}


@pytest.mark.parametrize(
    "redis_status,node_status,expected_status",
    [
        (_REDIS_GOOD, STATUS_GOOD, STATUS_GOOD),
        (_REDIS_GOOD, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_GOOD, STATUS_DEGRADED, STATUS_DEGRADED),
        (_REDIS_FAILED, STATUS_GOOD, STATUS_FAILED),
        (_REDIS_FAILED, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_FAILED, STATUS_DEGRADED, STATUS_FAILED),
        (_REDIS_DEGRADED, STATUS_GOOD, STATUS_DEGRADED),
        (_REDIS_DEGRADED, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_DEGRADED, STATUS_DEGRADED, STATUS_DEGRADED),
    ],
)
@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_redis_and_node_status_expectations(get, admin_api_client, full_service_hierarchy_controller, redis_status, node_status, expected_status):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"status": node_status})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=redis_status):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        assert controller['status'] == node_status
        redis = get_service_by_name(response.data, "redis")
        assert redis is not None
        assert redis['status'] == redis_status['status']
        assert response.data["status"] == expected_status


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_service_responds_with_invalid_status(get, admin_api_client, expected_log, full_service_hierarchy_controller):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"status": STATUS_GOOD})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value={'mode': 'testing', 'status': 'gibberish'}):
        with expected_log('aap_gateway_api.views.api.v1.status.logger', 'error', 'Got an unknown status for service redis: gibberish'):
            url = get_relative_url("status-view")
            response = admin_api_client.get(url)

            assert response.status_code == 200
            controller = get_service_by_name(response.data, "controller")
            assert controller is not None
            assert controller['status'] == STATUS_GOOD
            redis = get_service_by_name(response.data, "redis")
            assert redis is not None
            assert redis['response']['status'] == 'gibberish'
            assert response.data["status"] == STATUS_FAILED


def test_ensure_cluster_nodes_is_removed_from_clustered_redis(admin_api_client):
    clustered_return_value = {
        'mode': 'cluster',
        'status': 'good',
        'cluster_info': {
            'cluster_state': 'ok',
        },
        'cluster_nodes': {
            '172.24.0.5:6380': {
                'node_id': '645a2457ae1a2624311bb17cd75d7176be006178',
                'flags': 'slave',
            },
            '172.24.0.4:6380': {
                'node_id': '49d7c39281601a58e6acca82a6dc6a0e1cd5a3a2',
                'flags': 'myself,master',
            },
            '172.24.0.8:6380': {
                'node_id': '219999bcdd53c43a935622452e079499a17c7348',
                'flags': 'slave',
            },
            '172.24.0.7:6380': {
                'node_id': '9ae5aa23c5d1e8863095fdd1630c8e6cb933b41e',
                'flags': 'master',
            },
            '172.24.0.6:6380': {
                'node_id': '85b149ebac80c71de507a4adaa2e82bbf6b7de24',
                'flags': 'master',
            },
            '172.24.0.3:6380': {
                'node_id': 'cc0594acde6d3adb47f446ac985703bcb1dea282',
                'flags': 'slave',
            },
        },
    }
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=clustered_return_value):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        redis = get_service_by_name(response.data, "redis")
        assert redis is not None
        assert redis['response']['status'] == STATUS_GOOD
        assert 'nodes' in redis
        assert 'cluster_nodes' not in redis['response']
        assert response.data["status"] == STATUS_GOOD


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_multiple_nodes_get_truncated(get, admin_api_client, full_service_hierarchy_controller):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"status": STATUS_GOOD})

    # Create two duplicate address nodes
    ServiceNode.objects.create(
        name="Node 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )
    ServiceNode.objects.create(
        name="Node #2 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )

    assert ServiceNode.objects.filter(service_cluster=full_service_hierarchy_controller.service_cluster).count() == 3

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        # The cluster will appear as 3 nodes but there are really only 2 of them
        controller = get_service_by_name(response.data, "controller")
        assert controller is not None
        assert len(controller['nodes']) == 2


def slow_response(*args, **kwargs):
    start_time = time.time()
    time.sleep(3)
    end_time = time.time()
    return mock.Mock(status_code=200, json=lambda: {"status": STATUS_GOOD, 'start_time': start_time, 'end_time': end_time, 'duration': end_time - start_time})


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get", wraps=slow_response)
def test_that_get_requests_are_async(get, admin_api_client, full_service_hierarchy_controller):
    # Create two duplicate address nodes
    ServiceNode.objects.create(
        name="Node 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )
    ServiceNode.objects.create(
        name="Node #2 127.0.0.99",
        service_cluster=full_service_hierarchy_controller.service_cluster,
        address="127.0.0.99",
    )

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        start_time = time.time()
        response = admin_api_client.get(url)
        total_time = time.time() - start_time

        # We have 3 nodes will all take 3 seconds but they should run all at the same time.
        # So we want to make sure that we took > 3 second but < 9 (3 node * 3 seconds)
        assert total_time > 3 and total_time < 9, f"Total time was {total_time} and should have been < 9\n{response.data}"


@pytest.mark.parametrize(
    "console_return, side_effect, expected_status",
    [
        (mock.Mock(status_code=200, json=lambda: {"components": [{"name": "console.redhat.com", "status": "operational"}]}), None, STATUS_GOOD),
        (mock.Mock(status_code=200, json=lambda: {"components": [{"name": "console.redhat.com", "status": "failed"}]}), None, STATUS_FAILED),
        (mock.Mock(status_code=200, json=lambda: {"components": [{"name": "random", "status": "operational"}]}), None, STATUS_FAILED),
        (mock.Mock(status_code=200, json=lambda: {}), None, STATUS_FAILED),
        (None, Exception('Something went wrong'), STATUS_FAILED),
        (mock.Mock(status_code=400, json=lambda: {"status": "Bad request"}), None, STATUS_FAILED),
    ],
)
@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_console_status(get, console_return, side_effect, expected_status):
    get.return_value = console_return
    get.side_effect = side_effect

    resp = check_console()

    assert resp["status"] == expected_status

    if isinstance(side_effect, Exception):
        assert resp["exception"] == str(side_effect)
    else:
        assert resp["status"] == expected_status
        assert resp["response_code"] == console_return.status_code


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_includes_console(get, admin_api_client, settings_override_mutable, settings):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"components": [{"name": "console.redhat.com", "status": "operational"}]})
    sc = ServiceCluster.objects.create(name="Console", service_type=ServiceType.objects.get_or_create(name="console")[0])
    ServiceNode.objects.create(name="Console", service_cluster=sc)
    port = HTTPPort.objects.create(name="API Port", is_api_port=True, number=443)
    Route.objects.create(name="Console", http_port=port, service_cluster=sc, service_port=443, is_service_https=True, service_path="/", gateway_path="/")

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        status = get_service_by_name(response.data, "Console")
        assert status is not None
        assert status["status"] == STATUS_GOOD


@override_settings()
def test_missing_console_url(admin_api_client, settings_override_mutable, settings):
    del settings.CRC_STATUS_URL

    sc = ServiceCluster.objects.create(name="Console", service_type=ServiceType.objects.get_or_create(name="console")[0])
    ServiceNode.objects.create(name="Console", service_cluster=sc)
    port = HTTPPort.objects.create(name="API Port", is_api_port=True, number=443)
    Route.objects.create(name="Console", http_port=port, service_cluster=sc, service_port=443, is_service_https=True, service_path="/", gateway_path="/")

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")

        response = admin_api_client.get(url)
        status = get_service_by_name(response.data, "Console")
        assert 'nodes' in status
        node = next(iter(status['nodes'].values()))
        assert 'CRC_STATUS_URL not set' in node['body']


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_null_ping_url(get, admin_api_client):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"components": [{"name": "Pingless", "status": "good"}]})

    sc = ServiceCluster.objects.create(name="Pingless", service_type=ServiceType.objects.create(name="Pingless"))
    ServiceNode.objects.create(name="Pingless", service_cluster=sc, address='pingless.com')
    port = HTTPPort.objects.create(name="API Port", is_api_port=True, number=443)
    Route.objects.create(name="Pingless", http_port=port, service_cluster=sc, service_port=443, is_service_https=True, service_path="/", gateway_path="/")

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")

        admin_api_client.get(url)

    get.assert_called_once_with('https://pingless.com:443', verify=mock.ANY, timeout=mock.ANY)


def get_service_by_name(data: List, name: str):
    return next((s for s in data["services"] if s["service_name"] == name), None)
