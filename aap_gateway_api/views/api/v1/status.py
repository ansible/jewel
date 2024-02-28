from datetime import datetime

import requests
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from aap_gateway_api.models import Route, ServiceNode
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

ping_pages = {"gateway": "/api/gateway/v1/ping/", "hub": "/pulp/api/v3/status/", "controller": "/api/v2/ping/", "eda": "/_healthz"}


class StatusView(AnsibleBaseView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        current_time = datetime.now()
        response = {"time": current_time, "status": "good", "services": {}}

        routes = Route.objects.filter(enable_gateway_auth=True)
        for route in routes:
            service_type = route.service_cluster.get_service_type_display()
            if service_type not in response['services']:
                response['services'][service_type] = {}

            port_number = route.service_port
            http_or_s = 'https' if route.is_service_https else 'http'

            nodes = ServiceNode.objects.filter(service_cluster=route.service_cluster)
            for node in nodes:
                node_id = f'{node.address}:{port_number}'
                if node_id in response['services'][service_type]:
                    continue

                url = f"{http_or_s}://{node.address}:{port_number}{ping_pages[service_type]}"
                node_data = {
                    'url': url,
                    'status': 'Fine',
                }
                try:
                    timeout = get_preference_value('proxy', 'status_endpoint_backend_timeout_seconds')
                    node_response = requests.get(url, timeout=timeout)
                    if node_response.status_code != 200:
                        node_data['status'] = 'Failed'
                        node_data['response_code'] = node_response.status_code
                        node_data['body'] = node_response.text
                    else:
                        node_data['status'] = 'Good'
                        node_data['response'] = node_response.json()
                except Exception as e:
                    node_data['status'] = 'Failed'
                    node_data['exception'] = f'{e}'

                response['services'][service_type][node_id] = node_data

        return Response(response)
