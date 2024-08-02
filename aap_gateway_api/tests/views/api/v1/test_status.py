import time
from unittest import mock

import pytest
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import ServiceNode

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
        del response.data["services"]['redis']
        assert response.data["services"] == {}


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
        # The status ends up being degraded because we neither have good nor bad nodes in the service
        assert response.data["status"] == STATUS_DEGRADED
        assert 'controller' in response.data["services"]
        assert response.data["services"]["controller"] == {'status': STATUS_DEGRADED, 'nodes': {}}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_500(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.return_value = mock.Mock(status_code=500, text="test")
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_FAILED
        assert 'controller' in response.data["services"]
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert response.data["services"]["controller"]['nodes'][node_id]["status"] == STATUS_FAILED
        assert response.data["services"]["controller"]['nodes'][node_id]["response_code"] == 500
        assert response.data["services"]["controller"]['nodes'][node_id]["body"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_200(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        assert 'controller' in response.data["services"]
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert response.data["services"]["controller"]['nodes'][node_id]["status"] == STATUS_GOOD
        assert response.data["services"]["controller"]['nodes'][node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_full_hierarchy_with_exception(get, admin_api_client, full_service_hierarchy_controller):
    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        get.side_effect = Exception("test")
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data["status"] == STATUS_FAILED
        assert 'controller' in response.data["services"]
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert response.data["services"]["controller"]['nodes'][node_id]["status"] == STATUS_FAILED
        assert response.data["services"]["controller"]['nodes'][node_id]["exception"] == "test"


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_routes_same_service_cluster(get, admin_api_client, full_service_hierarchy_controller, http_port_factory, randname):
    """
    Test that the status endpoint can handle multiple routes to the same service cluster.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

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
        assert response.data["status"] == STATUS_GOOD, response.data
        assert 'controller' in response.data["services"]
        node_id = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert response.data["services"]["controller"]['nodes'][node_id]["status"] == STATUS_GOOD
        assert response.data["services"]["controller"]['nodes'][node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_multiple_service_nodes(get, admin_api_client, full_service_hierarchy_controller):
    """
    Test that the status endpoint can handle multiple service nodes pointing to the same service cluster.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

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
        assert 'controller' in response.data["services"]
        controller = response.data["services"]["controller"]

        assert len(controller['nodes']) == 3

        assert controller['status'] == STATUS_GOOD

        node_id_1 = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        node_id_2 = f"{new_service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        node_id_3 = f"{another_service_node.address}:{full_service_hierarchy_controller.route.service_port}"

        for node_id in (node_id_1, node_id_2, node_id_3):
            assert controller['nodes'][node_id]["status"] == STATUS_GOOD
            assert controller['nodes'][node_id]["response"] == {"test": "test"}


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_status_two_hierarchies(get, admin_api_client, full_service_hierarchy_controller, full_service_hierarchy_hub):
    """
    Test that the status endpoint can handle multiple complete service hierarchies.
    """
    get.return_value = mock.Mock(status_code=200, json=lambda: {"test": "test"})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=_REDIS_GOOD):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        assert response.data["status"] == STATUS_GOOD
        assert "controller" in response.data["services"]
        assert "hub" in response.data["services"]

        node_id_controller = f"{full_service_hierarchy_controller.service_node.address}:{full_service_hierarchy_controller.route.service_port}"
        assert response.data["services"]["controller"]['status'] == STATUS_GOOD
        assert response.data["services"]["controller"]['nodes'][node_id_controller]["status"] == STATUS_GOOD
        assert response.data["services"]["controller"]['nodes'][node_id_controller]["response"] == {"test": "test"}

        node_id_hub = f"{full_service_hierarchy_hub.service_node.address}:{full_service_hierarchy_hub.route.service_port}"
        assert response.data["services"]["hub"]['status'] == STATUS_GOOD
        assert response.data["services"]["hub"]['nodes'][node_id_hub]["status"] == STATUS_GOOD
        assert response.data["services"]["hub"]['nodes'][node_id_hub]["response"] == {"test": "test"}


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
        assert response.data["services"]["controller"]['status'] == node_status
        assert response.data["services"]["redis"]['status'] == redis_status['status']
        assert response.data["status"] == expected_status


@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_service_responds_with_invalid_status(get, admin_api_client, expected_log, full_service_hierarchy_controller):
    get.return_value = mock.Mock(status_code=200, json=lambda: {"status": STATUS_GOOD})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value={'mode': 'testing', 'status': 'gibberish'}):
        with expected_log('aap_gateway_api.views.api.v1.status.logger', 'error', 'Got an unknown status for redis: gibberish'):
            url = get_relative_url("status-view")
            response = admin_api_client.get(url)

            assert response.status_code == 200
            assert response.data["services"]["controller"]['status'] == STATUS_GOOD
            assert response.data["services"]["redis"]['status'] == 'gibberish'
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
        assert response.data["services"]["redis"]['status'] == STATUS_GOOD
        assert 'nodes' in response.data["services"]["redis"]
        assert 'cluster_nodes' not in response.data["services"]["redis"]
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
        assert len(response.data["services"]["controller"]['nodes']) == 2


@pytest.mark.parametrize(
    "redis_status,eda_node_status,expected_eda_status",
    [
        (_REDIS_GOOD, STATUS_GOOD, STATUS_GOOD),
        (_REDIS_GOOD, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_GOOD, STATUS_DEGRADED, STATUS_DEGRADED),
        (_REDIS_FAILED, STATUS_GOOD, STATUS_DEGRADED),
        (_REDIS_FAILED, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_FAILED, STATUS_DEGRADED, STATUS_DEGRADED),
        (_REDIS_DEGRADED, STATUS_GOOD, STATUS_GOOD),
        (_REDIS_DEGRADED, STATUS_FAILED, STATUS_FAILED),
        (_REDIS_DEGRADED, STATUS_DEGRADED, STATUS_DEGRADED),
    ],
)
@mock.patch("aap_gateway_api.views.api.v1.status.requests.get")
def test_eda_status_gets_degraded_if_redis_down(get, redis_status, eda_node_status, expected_eda_status, admin_api_client, full_service_hierarchy_eda):
    if eda_node_status == STATUS_DEGRADED:
        # Since we want a degraded status we need to do 2 things:
        #     1. Add another node to the service "cluster"
        #     2. Make the get call return one good status and one bad status
        ServiceNode.objects.create(
            name="Node 127.0.0.99",
            service_cluster=full_service_hierarchy_eda.service_cluster,
            address="127.0.0.99",
        )

        get.side_effect = [
            mock.Mock(status_code=200, json=lambda: {"status": STATUS_GOOD}),
            mock.Mock(status_code=200, json=lambda: {"status": STATUS_FAILED}),
        ]
    else:
        get.return_value = mock.Mock(status_code=200, json=lambda: {"status": eda_node_status})

    with mock.patch('aap_gateway_api.views.api.v1.status.get_redis_status', return_value=redis_status):
        url = get_relative_url("status-view")
        response = admin_api_client.get(url)

        assert response.status_code == 200
        assert response.data["services"]["eda"]['status'] == expected_eda_status
        assert response.data["services"]["redis"]['status'] == redis_status['status']


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
