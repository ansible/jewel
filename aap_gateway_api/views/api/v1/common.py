from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from rest_framework import viewsets


class GatewayModelViewSet(viewsets.ModelViewSet, AnsibleBaseView):
    pass
