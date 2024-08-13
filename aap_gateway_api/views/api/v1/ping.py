from datetime import datetime
from urllib.parse import urljoin

import requests
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_GOOD
from django.db import connections
from rest_framework.response import Response

from aap_gateway_api.utils import get_preference_value
from aap_gateway_api.version import get_aap_version
from aap_gateway_api.views.api.v1.common import AnsibleBaseView


def _get_db_connection_status(db_conn):
    try:
        db_conn.cursor()
        return {'db_connected': True}
    except Exception as e:
        # We only log the exception type because the message could contain sensitive information
        return {'db_connected': False, 'db_exception': type(e).__name__, 'status': STATUS_DEGRADED}


class PingView(AnsibleBaseView):
    permission_classes = []

    def get(self, request):
        current_time = datetime.now()
        response = {
            "version": get_aap_version(),
            "pong": str(current_time),
            "status": STATUS_GOOD,
        }

        # Attempt a db connection
        db_info = _get_db_connection_status(connections['default'])
        response.update(db_info)

        # Check the proxy
        ping_url = urljoin(get_preference_value('proxy', 'gateway_proxy_url'), '/up')
        ignore_cert = get_preference_value('proxy', 'gateway_proxy_url_ignore_cert')
        try:
            proxy_response = requests.request("GET", ping_url, verify=(not ignore_cert))
            if proxy_response.status_code == 200:
                connected = True
            else:
                connected = False
                response['proxy_status_code'] = proxy_response.status_code
                response['status'] = STATUS_DEGRADED
        except Exception as e:
            # Exception might expose the host names so we don't want to add a reason for the exception
            connected = False
            # We only log the exception type because the message could contain sensitive information
            response['proxy_exception_type'] = type(e).__name__
            response['status'] = STATUS_DEGRADED
        response['proxy_connected'] = connected

        return Response(response)
