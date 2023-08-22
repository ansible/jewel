import json
from unittest import mock

import pytest
from aap.gateway.views import GatewayVersionView, LoggedGatewayLoginView


class TestLoggedGatewayLoginView:
    @pytest.mark.parametrize(('is_authorized,return_code'), [(True, 200), (False, 401)])
    @mock.patch('django.contrib.auth.login', mock.MagicMock())
    def test_get_logged_in(self, is_authorized, return_code, mocked_http):
        my_view = LoggedGatewayLoginView()
        request = mocked_http.mocked_gateway_view_get_request(is_authorized)
        response = my_view.get(request)
        assert response.status_code == return_code


class TestGatewayVersionView:
    @pytest.mark.parametrize(('is_authorized,return_code'), [(True, 200), (False, 403)])
    def test_version_view(self, is_authorized, return_code, mocked_http):
        my_view = GatewayVersionView()
        request = mocked_http.mocked_gateway_view_get_request(is_authorized)
        response = my_view.get(request)
        assert response.status_code == return_code
        if return_code == 200:
            data = json.loads(response.content)
            assert 'package' in data and data['package'] == 'aap'
            assert 'version' in data
