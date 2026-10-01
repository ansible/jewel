from unittest.mock import patch

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


@patch("aap_gateway_api.apps._clear_xds_cache_on_startup")
@patch("dispatcherd.config.setup")
@patch("django.db.models.signals.post_migrate.connect")
@patch("dynamic_preferences.signals.preference_updated.connect")
def test_ready_invokes_xds_cache_clearing_on_server_startup(mock_pref_updated_connect, mock_post_migrate_connect, mock_dispatcherd_setup, mock_clear_xds_cache):
    from aap_gateway_api.apps import MyAppConfig

    MyAppConfig._xds_cache_cleared = False
    config = MyAppConfig.create("aap_gateway_api")

    with patch.object(config, "_is_server_startup", return_value=True):
        config.ready()

    mock_clear_xds_cache.assert_called_once()


@patch("aap_gateway_api.apps._clear_xds_cache_on_startup")
@patch("dispatcherd.config.setup")
@patch("django.db.models.signals.post_migrate.connect")
@patch("dynamic_preferences.signals.preference_updated.connect")
def test_ready_only_clears_cache_once_when_called_multiple_times(
    mock_pref_updated_connect, mock_post_migrate_connect, mock_dispatcherd_setup, mock_clear_xds_cache
):
    from aap_gateway_api.apps import MyAppConfig

    MyAppConfig._xds_cache_cleared = False
    config = MyAppConfig.create("aap_gateway_api")

    with patch.object(config, "_is_server_startup", return_value=True):
        config.ready()
        config.ready()
        config.ready()

    mock_clear_xds_cache.assert_called_once()


@patch("aap_gateway_api.apps._clear_xds_cache_on_startup")
@patch("dispatcherd.config.setup")
@patch("django.db.models.signals.post_migrate.connect")
@patch("dynamic_preferences.signals.preference_updated.connect")
def test_ready_skips_cache_clearing_for_management_commands(mock_pref_updated_connect, mock_post_migrate_connect, mock_dispatcherd_setup, mock_clear_xds_cache):
    from aap_gateway_api.apps import MyAppConfig

    MyAppConfig._xds_cache_cleared = False
    config = MyAppConfig.create("aap_gateway_api")

    with patch.object(config, "_is_server_startup", return_value=False):
        config.ready()

    mock_clear_xds_cache.assert_not_called()


def test_is_server_startup_returns_true_for_runserver():
    import sys

    from aap_gateway_api.apps import MyAppConfig

    config = MyAppConfig.create("aap_gateway_api")
    original_argv = sys.argv

    try:
        sys.argv = ["manage.py", "runserver"]
        assert config._is_server_startup() is True
    finally:
        sys.argv = original_argv


def test_is_server_startup_returns_false_for_management_commands():
    import sys

    from aap_gateway_api.apps import MyAppConfig

    config = MyAppConfig.create("aap_gateway_api")
    original_argv = sys.argv

    try:
        sys.argv = ["manage.py", "migrate"]
        assert config._is_server_startup() is False

        sys.argv = ["manage.py", "showmigrations"]
        assert config._is_server_startup() is False

        sys.argv = ["manage.py", "collectstatic"]
        assert config._is_server_startup() is False
    finally:
        sys.argv = original_argv


def test_is_server_startup_returns_true_when_uwsgi_available():
    from unittest.mock import MagicMock

    from aap_gateway_api.apps import MyAppConfig

    config = MyAppConfig.create("aap_gateway_api")

    # Mock uwsgi module being available
    import sys

    fake_uwsgi = MagicMock()
    original_modules = sys.modules.copy()

    try:
        sys.modules["uwsgi"] = fake_uwsgi
        assert config._is_server_startup() is True
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)
