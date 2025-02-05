from datetime import datetime

import requests
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_GOOD
from django.conf import settings
from rest_framework.response import Response

from aap_gateway_api.models import HTTPPort
from aap_gateway_api.utils.db import get_db_connection_status
from aap_gateway_api.version import get_aap_version
from aap_gateway_api.views.api.v1.common import AnsibleBaseView


class PingView(AnsibleBaseView):
    permission_classes = []

    def get(self, request):
        timeout = getattr(settings, "PING_PAGE_CHECK_TIMEOUT", 5)
        ignore_cert = getattr(settings, "PING_PAGE_CHECK_IGNORE_CERT", False)

        current_time = datetime.now()
        response = {
            "version": get_aap_version(),
            "pong": str(current_time),
            "status": STATUS_GOOD,
        }

        try:
            db_status = get_db_connection_status('default', timeout)
            response['db_connected'] = db_status
        except Exception as e:
            response.update({'db_connected': False, 'db_exception': type(e).__name__, 'status': STATUS_DEGRADED})

        # Check the proxy (skip for unit tests)
        http_port = HTTPPort.objects.filter(is_api_port=True).first()
        if http_port:
            ping_url = f"{'https' if http_port.use_https else 'http'}://{settings.ENVOY_HOSTNAME}:{http_port.number}/up"
            try:
                proxy_response = requests.request("GET", ping_url, verify=(not ignore_cert), timeout=timeout)
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
