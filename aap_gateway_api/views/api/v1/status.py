import logging
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Iterator, List

import requests
from ansible_base.lib.cache.fallback_cache import PRIMARY_CACHE
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.redis.client import get_redis_status
from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from aap_gateway_api.models import Route, ServiceNode
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.api.v1.status')
ServiceCheck = namedtuple('ServiceCheck', ['service_type', 'node_id', 'url', 'timeout', 'verify', 'response'])


def check_redis(timeout: int = 4) -> Dict:
    if getattr(settings, 'CACHES', {}).get('default', {}).get('BACKEND', None) == 'ansible_base.lib.cache.fallback_cache.DABCacheWithFallback':
        redis_settings = getattr(settings, 'CACHES', {}).get(PRIMARY_CACHE)
    else:
        redis_settings = getattr(settings, 'CACHES', {}).get('default')

    url = redis_settings['LOCATION']
    kwargs = redis_settings['OPTIONS'].get('CLIENT_CLASS_KWARGS', {})
    status = get_redis_status(url=url, timeout=timeout, **kwargs)

    return status


def check_node(server_data: ServiceCheck) -> ServiceCheck:
    service, node, url, timeout, verify, _ = server_data
    response: Dict
    if service == 'redis':
        status = check_redis(timeout)
        response = {'status': status["status"], 'url': "", 'response': status}
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

    return ServiceCheck(service_type=service, node_id=node, url=url, timeout=timeout, verify=verify, response=response)


def process_statuses(response: Dict) -> Dict:
    # Aggregate a status for services from its nodes
    good_services = 0
    bad_services = 0
    degraded_services = 0
    for service in response['services']:
        service_name = service['service_type']

        # If we don't know the status for the service than try to get it from the nodes
        if service['status'] == 'Unknown':
            good_nodes = 0
            bad_nodes = 0
            for node in service['nodes']:
                node_status = service['nodes'][node].get('status', 'Unknown')
                response_status = service['nodes'][node].get('response', {}).get('status', None)
                # response status takes prescience over node_status
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
                        f"Got an unknown status for service {service_name} from node {node}: {overall_status} from request {response_status} and {node_status}"
                    )
                    bad_nodes = bad_nodes + 1

            # Determine the service status based on the node statuses
            if good_nodes > 0 and bad_nodes == 0:
                service['status'] = STATUS_GOOD
            elif good_nodes == 0 and bad_nodes > 0:
                service['status'] = STATUS_FAILED
            else:
                service['status'] = STATUS_DEGRADED

            logger.debug(f"For {service_name} got {good_nodes} good nodes and {bad_nodes} bad nodes, overall status is {service['status']}")

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

    # Special check, if the service is EDA and redis is "down" EDA needs to be DEGRADED
    eda = next((s for s in response['services'] if s['service_type'] == 'eda'), None)
    redis = next((s for s in response['services'] if s['service_type'] == 'redis'), None)
    if eda and redis and eda['status'] != STATUS_FAILED and redis['status'] == STATUS_FAILED:
        eda['status'] = STATUS_DEGRADED

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
            if next((True for check in processes if check.service_type == service_name and check.node_id == node_id), False):
                continue
            else:
                processes.append(
                    ServiceCheck(
                        service_type=service_name,
                        node_id=node_id,
                        url=f"{'https' if route.is_service_https else 'http'}://{node.address}:{service_port}{service_type.ping_url}",
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
        service = result.service_type
        # find a service to add node to, create one if none exists
        current_service = next((s for s in response['services'] if s['service_type'] == service), None)
        if current_service is None:
            current_service = {'service_type': service, 'status': 'Unknown', 'nodes': {}}
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
        service_type = service['service_type']
        del service['service_type']
        new_services[service_type] = service
    return new_services


class StatusView(AnsibleBaseView):
    """API endpoint that shows status of platform services."""

    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "service_keys", OpenApiTypes.BOOL, OpenApiParameter.QUERY, description="Use a dictionary to describe services instead of a list", required=False
            )
        ]
    )
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
        processes.append(ServiceCheck(service_type='redis', node_id='redis', url='', timeout=timeout, verify=verify, response=None))

        results: Iterator[ServiceCheck]
        with ThreadPoolExecutor() as executor:
            # no need for timeout for executor, all requests have their own  timeouts
            results = executor.map(check_node, processes)

        response = create_response(results)

        if services_format_with_keys:
            new_services = services_to_dict(response['services'])
            del response['services']
            response['services'] = new_services

        # Return the response
        return Response(response)
