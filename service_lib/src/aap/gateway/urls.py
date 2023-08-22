from aap.gateway.views import GatewayVersionView, LoggedGatewayLoginView
from django.urls import re_path


class GatewayURLs:
    def __init__(self, login_view_class=LoggedGatewayLoginView):
        self.login_view_class = login_view_class

    def get_url_list(self):
        urls = []
        urls.append(re_path(r'^gateway/login/$', self.login_view_class.as_view(), name='gateway_login'))
        urls.append(re_path(r'^gateway/version/$', GatewayVersionView.as_view(), name='gateway_version'))
        return urls
