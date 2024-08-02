import logging
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict

import requests
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.redis.client import get_redis_status
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from rest_framework.response import Response

from aap_gateway_api.models import Route, ServiceNode
from aap_gateway_api.models.service import SERVICE_PING_PAGES
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.api.v1.status')
ServiceCheck = namedtuple('ServiceCheck', ['service_type', 'node_id', 'url', 'timeout', 'verify'])


def check_redis(timeout: int = 4) -> Dict:
    cache = getattr(settings, 'CACHES', {}).get('default')
    url = cache['LOCATION']
    kwargs = cache['OPTIONS'].get('CLIENT_CLASS_KWARGS', {})
    status = get_redis_status(url=url, timeout=timeout, **kwargs)

    # Move the cluster_nodes redis object to "nodes" for alignment
    if 'cluster_nodes' in status:
        status['nodes'] = status['cluster_nodes']
        del status['cluster_nodes']

    return {'service': 'redis', 'status': status}


def check_node(server_data: ServiceCheck) -> Dict:
    service, node, url, timeout, verify = server_data
    if service == 'redis':
        return check_redis(timeout)

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

    return {'service': service, 'node': node, 'status': node_status}


def process_statuses(response: Dict) -> Dict:
    # Aggregate a status for services from its nodes
    good_services = 0
    bad_services = 0
    degraded_services = 0
    for service_name in response['services']:
        service = response['services'][service_name]

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
            logger.error(f"Got an unknown status for {service_name}: {service['status']}")
            bad_services = bad_services + 1

    # Special check, if the service is EDA and redis is "down" EDA needs to be DEGRADED
    eda = response['services'].get('eda', None)
    redis = response['services'].get('redis', None)
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


class StatusView(AnsibleBaseView):
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]

    def get(self, request):
        # We can't pull preferences or models in async functions
        # So we will construct our response object here and pass that around

        # Get some settings
        timeout = get_preference_value('proxy', 'status_endpoint_backend_timeout_seconds', 4)
        verify = get_preference_value('proxy', 'status_endpoint_backend_verify', True)

        # Start response object
        current_time = datetime.now()
        response = {"time": current_time, "status": STATUS_GOOD, "services": {}}
        routes = Route.objects.filter(enable_gateway_auth=True)
        redis_service_check = ServiceCheck(service_type='redis', node_id=None, url=None, timeout=timeout, verify=verify)
        processes = [redis_service_check]
        for route in routes:
            service_type = route.service_cluster.get_service_type_display()
            response['services'][service_type] = {'status': 'Unknown', 'nodes': {}}
            port_number = route.service_port
            http_or_s = 'https' if route.is_service_https else 'http'
            nodes = ServiceNode.objects.filter(service_cluster=route.service_cluster)
            for node in nodes:
                node_id = f'{node.address}:{port_number}'
                if node_id in response['services'][service_type]['nodes']:
                    continue

                url = f"{http_or_s}://{node.address}:{port_number}{SERVICE_PING_PAGES[service_type]}"
                response['services'][service_type]['nodes'][node_id] = {
                    'url': url,
                    'status': 'Unknown',
                }
                service_check = ServiceCheck(service_type=service_type, node_id=node_id, url=url, timeout=timeout, verify=verify)
                processes.append(service_check)

        with ThreadPoolExecutor() as executor:
            results = executor.map(check_node, processes, timeout=timeout)

            for result in results:
                status = result['status']
                service = result['service']
                node = result.get('node', None)
                if result['service'] == 'redis':
                    response['services']['redis'] = status
                else:
                    response['services'][service]['nodes'][node] = status

        # Return the response
        return Response(process_statuses(response))
