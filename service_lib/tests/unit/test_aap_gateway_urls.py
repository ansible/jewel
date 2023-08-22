from unittest import mock

from aap.gateway.urls import GatewayURLs


class TestGatewayURLs:
    def test_get_url_list(self):
        url_generator = GatewayURLs()
        url_list = url_generator.get_url_list()
        assert len(url_list) == 2

    def test_get_url_list_override(self):
        mock_class_1 = mock.MagicMock()
        url_generator = GatewayURLs(login_view_class=mock_class_1)
        assert url_generator.login_view_class == mock_class_1
