from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from aap_gateway_api.views.api.envoy.rest_control_plane import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS


@pytest.mark.django_db
def test_clear_xds_cache_on_startup_removes_only_xds_entries():
    from aap_gateway_api.apps import _clear_xds_cache_on_startup

    cache.set(XDS_CACHE_KEY_CDS, {"clusters": []})
    cache.set(XDS_CACHE_KEY_LDS, {"listeners": []})
    cache.set(XDS_CACHE_KEY_SDS, {"resources": []})
    cache.set("unrelated", "preserved")

    _clear_xds_cache_on_startup()

    assert cache.get(XDS_CACHE_KEY_CDS) is None
    assert cache.get(XDS_CACHE_KEY_LDS) is None
    assert cache.get(XDS_CACHE_KEY_SDS) is None
    assert cache.get("unrelated") == "preserved"


@pytest.mark.django_db
@patch("aap_gateway_api.apps._clear_xds_cache_on_startup")
@patch("dispatcherd.config.setup")
def test_ready_invokes_xds_cache_clearing(mock_dispatcherd_setup, mock_clear_xds_cache):
    from aap_gateway_api.apps import MyAppConfig

    MyAppConfig._xds_cache_cleared = False
    config = MyAppConfig("aap_gateway_api", MagicMock())
    config.ready()

    mock_clear_xds_cache.assert_called_once()


@pytest.mark.django_db
@patch("aap_gateway_api.apps._clear_xds_cache_on_startup")
@patch("dispatcherd.config.setup")
def test_ready_only_clears_cache_once_when_called_multiple_times(mock_dispatcherd_setup, mock_clear_xds_cache):
    from aap_gateway_api.apps import MyAppConfig

    MyAppConfig._xds_cache_cleared = False
    config = MyAppConfig("aap_gateway_api", MagicMock())
    config.ready()
    config.ready()
    config.ready()

    mock_clear_xds_cache.assert_called_once()
