from importlib import reload
from unittest import mock

import pytest
from django.test import override_settings


@pytest.mark.parametrize(
    "setting",
    [
        True,
        False,
    ],
)
def test_ddt_urls(setting):
    with override_settings(ENABLE_DJANGO_DEBUG_TOOLBAR=setting):
        with mock.patch('debug_toolbar.toolbar.debug_toolbar_urls', return_value=['added']):
            import aap_gateway_api.urls

            reload(aap_gateway_api.urls)

            found_url = 'added' in aap_gateway_api.urls.urlpatterns
            assert found_url is setting
