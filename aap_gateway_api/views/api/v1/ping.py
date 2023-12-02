from datetime import datetime
from urllib.parse import urljoin

import requests
from django.db import connections
from django.db.utils import OperationalError
from rest_framework.response import Response

from aap_gateway_api.utils import get_preference_value
from aap_gateway_api.views.api.v1.common import ViewWithHeaders


class PingView(ViewWithHeaders):
    permission_classes = []

    def get(self, request):
        current_time = datetime.now()
        response = {
            "pong": str(current_time),
            "status": "good",
        }

        # Attempt a db connection
        db_conn = connections['default']
        try:
            db_conn.cursor()
        except OperationalError as e:
            connected = False
            response['db_exception'] = type(e).__name__
            response['status'] = "degraded"
        else:
            connected = True
        response['db_connected'] = connected

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
                response['status'] = "degraded"
        except Exception as e:
            # Exception might expose the host names so we don't want to add a reason for the exception
            connected = False
            response['proxy_exception'] = type(e).__name__
            response['status'] = "degraded"
        response['proxy_connected'] = connected

        return Response(response)
