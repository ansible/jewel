import logging
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Iterator, List, Literal

import requests
from ansible_base.lib.cache.fallback_cache import PRIMARY_CACHE
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.redis.client import get_redis_status
from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema
from rest_framework.response import Response

from aap_gateway_api.models import Route, ServiceNode
from aap_gateway_api.serializers.status import ServiceKeysStatusSerializer, StatusSerializer
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.api.v1.status')
ServiceCheck = namedtuple('ServiceCheck', ['service_name', 'service_type', 'node_id', 'url', 'timeout', 'verify', 'response'])

CONSOLE_SERVICE = "console.redhat.com"


def check_redis(timeout: int = 4) -> Dict:
    if getattr(settings, 'CACHES', {}).get('default', {}).get('BACKEND', None) == 'ansible_base.lib.cache.fallback_cache.DABCacheWithFallback':
        redis_settings = getattr(settings, 'CACHES', {}).get(PRIMARY_CACHE)
    else:
        redis_settings = getattr(settings, 'CACHES', {}).get('default')

    url = redis_settings['LOCATION']

    if url.startswith('unix://'):
        return _check_redis_unix_socket(url, timeout)

    kwargs = redis_settings['OPTIONS'].get('CLIENT_CLASS_KWARGS', {})
    status = get_redis_status(url=url, timeout=timeout, **kwargs)

    return status


def _check_redis_unix_socket(url: str, timeout: int) -> Dict:
    import redis as redis_lib

    try:
        parsed = redis_lib.connection.parse_url(url)
        r = redis_lib.Redis(
            unix_socket_path=parsed.get('unix_socket_path', '/var/run/redis/redis.sock'),
            db=parsed.get('db', 0),
            socket_timeout=timeout,
            protocol=2,
        )
        r.ping()
        return {'mode': 'standalone', 'status': STATUS_GOOD}
    except Exception as e:
        logger.error(f"Failed checking sidecar Redis health: {e}")
        return {'mode': 'standalone', 'status': STATUS_FAILED, 'exception': str(e)}


def check_console(timeout: int = 4) -> Dict:
    result = {"name": CONSOLE_SERVICE, "status": STATUS_FAILED}
    if not hasattr(settings, 'CRC_STATUS_URL') or not settings.CRC_STATUS_URL:
        logger.error("Console service defined, but CRC_STATUS_URL not set!")
        result["body"] = "CRC_STATUS_URL not set"
        return result
    try:
        response = requests.get(settings.CRC_STATUS_URL, timeout=timeout)
        result['response_code'] = response.status_code
        if response.status_code != 200:
            result['status'] = STATUS_FAILED
            result['body'] = response.text
            return result

        response_json = response.json()
        console_status = next(status for status in response_json["components"] if status["name"] == CONSOLE_SERVICE)
        result["status"] = STATUS_GOOD if console_status["status"] == "operational" else console_status["status"]
    except Exception as e:
        result['status'] = STATUS_FAILED
        result['exception'] = f'{e}'
    return result


def check_node(server_data: ServiceCheck) -> ServiceCheck:
    service, service_type, node, url, timeout, verify, _ = server_data
    response: Dict
    if service == 'redis':
        status = check_redis(timeout)
        response = {'status': status["status"], 'url': "", 'response': status}
    elif service_type == 'console':
        response = check_console(timeout)
    else:
        node_status = {'url': url}
        try:
            node_response = requests.get(url, timeout=timeout, verify=verify)
            if node_response.status_code != 200:
                node_status['status'] = STATUS_FAILED
                node_status['response_code'] = node_response.status_code
                node_status['body'] = node_response.text
            else:
                node_status['status'] = STATUS_GOOD
                node_status['response'] = node_response.json()
        except Exception as e:
            node_status['status'] = STATUS_FAILED
            node_status['exception'] = f'{e}'
        response = node_status

    return ServiceCheck(service_name=service, service_type=service_type, node_id=node, url=url, timeout=timeout, verify=verify, response=response)


def _get_good_and_bad_node_counts(service: dict) -> tuple[int, int]:
    good_nodes = 0
    bad_nodes = 0
    for node in service['nodes']:
        node_status = service['nodes'][node].get('status', 'Unknown')
        response_status = service['nodes'][node].get('response', {}).get('status', None)
        # response status takes precedence over node_status
        if response_status:
            if response_status == 'OK':  # EDA status
                overall_status = STATUS_GOOD
            else:
                overall_status = response_status
            service['nodes'][node]['status'] = overall_status
        else:
            overall_status = node_status

        if overall_status == STATUS_GOOD:
            good_nodes = good_nodes + 1
        elif overall_status == STATUS_FAILED:
            bad_nodes = bad_nodes + 1
        elif overall_status != STATUS_DEGRADED:
            logger.error(
                f"Got an unknown status for service {service['service_name']} from node {node}: "
                f"{overall_status} from request {response_status} and {node_status}"
            )
            bad_nodes = bad_nodes + 1
    return good_nodes, bad_nodes


def _determine_service_status(service: Dict) -> Literal["good", "failed", "degraded"]:
    """
    Determine a service status by using its node statuses
    """
    good_nodes, bad_nodes = _get_good_and_bad_node_counts(service)
    if good_nodes > 0 and bad_nodes == 0:
        service_status = STATUS_GOOD
    elif good_nodes == 0 and bad_nodes > 0:
        service_status = STATUS_FAILED
    else:
        service_status = STATUS_DEGRADED

    logger.debug(f"For {service['service_name']} got {good_nodes} good nodes and {bad_nodes} bad nodes, overall status is {service_status}")

    return service_status


def process_statuses(response: Dict) -> Dict:
    """
    This method determines the overall status for AAP based on service statuses.
    If service statuses are unavailable, we infer a service status from its node statuses
    """
    good_services = 0
    bad_services = 0
    degraded_services = 0
    for service in response['services']:
        service_name = service['service_name']

        # If we don't know the status for the service then try to get it from the nodes
        if service['status'] == 'Unknown':
            service['status'] = _determine_service_status(service)

        # Now that we either had the status or we generated it, lets see how the service status contributes to the overall status
        if service['status'] == STATUS_FAILED:
            bad_services = bad_services + 1
        elif service['status'] == STATUS_DEGRADED:
            degraded_services = degraded_services + 1
        elif service['status'] == STATUS_GOOD:
            good_services = good_services + 1
        else:
            logger.error(f"Got an unknown status for service {service_name}: {service['status']}")
            bad_services = bad_services + 1

    # Determine the overall status for AAP based on service statuses
    if bad_services > 0:
        response['status'] = STATUS_FAILED
    elif degraded_services > 0:
        response['status'] = STATUS_DEGRADED
    else:
        response['status'] = STATUS_GOOD

    return response


def get_services(timeout: int = 10, verify: bool = True) -> List[ServiceCheck]:
    processes: List[ServiceCheck] = []

    routes = Route.objects.filter(enable_gateway_auth=True)
    for route in routes:
        service_name = route.service_cluster.name
        service_type = route.service_cluster.service_type
        service_port = route.service_port
        service_nodes = ServiceNode.objects.filter(service_cluster=route.service_cluster)
        for node in service_nodes:
            node_id = f'{node.address}:{service_port}'
            if next((True for check in processes if check.service_name == service_name and check.node_id == node_id), False):
                continue

            url = f"{'https' if route.is_service_https else 'http'}://{node.address}:{service_port}"
            # ping_url is nullable
            if service_type.ping_url:
                url = f"{url}{service_type.ping_url}"

            processes.append(
                ServiceCheck(
                    service_name=service_name,
                    service_type=service_type.name,
                    node_id=node_id,
                    url=url,
                    timeout=timeout,
                    verify=verify,
                    response=None,
                )
            )
    return processes


def create_response(service_checks_with_results: Iterator[ServiceCheck]) -> Dict:
    # Start response object
    response = {"time": datetime.now(), "status": STATUS_GOOD, "services": []}

    for result in service_checks_with_results:
        service = result.service_name
        # find a service to add node to, create one if none exists
        current_service = next((s for s in response['services'] if s['service_name'] == service), None)
        if current_service is None:
            current_service = {'service_name': service, 'status': 'Unknown', 'nodes': {}}
            response['services'].append(current_service)
        # special handling for redis, pulling up the status from response and cluster_nodes into nodes
        if service == 'redis':
            current_service['status'] = result.response['status']
            if 'cluster_nodes' in result.response['response']:
                current_service['nodes'] = result.response['response']['cluster_nodes']
                del result.response['response']['cluster_nodes']
            current_service['response'] = result.response['response']
        else:
            current_service['nodes'][result.node_id] = result.response

    return process_statuses(response)


def services_to_dict(services: List[Dict]) -> Dict:
    new_services = {}
    for service in services:
        service_name = service['service_name']
        del service['service_name']
        new_services[service_name] = service
    return new_services


# NOTE: If the response format for /status is changed, please update
# aap_gateway_api/serializers/status.py content to match
@extend_schema(
    parameters=[
        OpenApiParameter(
            "service_keys", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="Use a dictionary to describe services instead of a list", required=False
        )
    ],
    responses=PolymorphicProxySerializer(
        component_name='StatusResponseOptions',
        serializers=[StatusSerializer, ServiceKeysStatusSerializer],
        resource_type_field_name=None,
    ),
)
class StatusView(AnsibleBaseView):
    """API endpoint that shows status of platform services."""

    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]

    def get(self, request):
        # We can't pull preferences or models in async functions
        # So we will construct our response object here and pass that around

        # Get some settings
        timeout = get_preference_value('proxy', 'status_endpoint_backend_timeout_seconds')
        verify = get_preference_value('proxy', 'status_endpoint_backend_verify')
        # get setting for formatting services as an object from request params
        service_keys = request.query_params.get('service_keys', None)
        if service_keys is not None:
            try:
                services_format_with_keys = to_python_boolean(service_keys, allow_none=False)
            except ValueError:
                services_format_with_keys = False
        else:
            services_format_with_keys = False

        # Get processes
        processes = get_services(timeout=timeout, verify=verify)

        # Add redis service check
        processes.append(ServiceCheck(service_name='redis', service_type='redis', node_id='redis', url='', timeout=timeout, verify=verify, response=None))

        results: Iterator[ServiceCheck]
        with ThreadPoolExecutor() as executor:
            # no need for timeout for executor, all requests have their own  timeouts
            results = executor.map(check_node, processes)

        response = create_response(results)

        if services_format_with_keys:
            new_services = services_to_dict(response['services'])
            del response['services']
            response['services'] = new_services
            serialized = ServiceKeysStatusSerializer(response)
        else:
            serialized = StatusSerializer(response)

        # Return the response
        return Response(serialized.data)
