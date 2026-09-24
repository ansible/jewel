from django.apps import AppConfig
from django.db.models import signals
from dynamic_preferences.signals import preference_updated


def _initialize_data(sender, **kwargs):
    from aap_gateway_api.signals.preloaded_data import create_preload_data

    create_preload_data(**kwargs)


def _initialize_preferences(sender, **kwargs):
    from aap_gateway_api.utils.preferences import initialize_preferences

    initialize_preferences()


def _notify_on_preference_update(sender, section, name, old_value, new_value, **kwargs):
    """
    This signal gets called when a preference is updated. We use it to call the on_update
    method of the preference if it exists. This means we don't have to hardcode preference
    names and sections here in the signal handler.
    """
    from aap_gateway_api.preferences import gateway_preference_registry

    preference = gateway_preference_registry.get(name, section)
    if preference.on_update:
        preference.on_update(old_value, new_value)


def _clear_xds_cache_on_startup():
    from aap_gateway_api.views.api.envoy.rest_control_plane import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, invalidate_xds_cache

    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


class MyAppConfig(AppConfig):
    name = "aap_gateway_api"
    verbose_name = "Gateway"
    _xds_cache_cleared = False

    def ready(self):
        signals.post_migrate.connect(_initialize_preferences, sender=self, weak=False)
        signals.post_migrate.connect(_initialize_data, sender=self, weak=False)
        preference_updated.connect(_notify_on_preference_update)

        from dispatcherd.config import setup as dispatcherd_setup

        from aap_gateway_api.dispatch.config import get_dispatcherd_config

        dispatcherd_setup(get_dispatcherd_config())

        if not MyAppConfig._xds_cache_cleared and self._is_server_startup():
            _clear_xds_cache_on_startup()
            MyAppConfig._xds_cache_cleared = True

        # Load the signals and feature flag conditions
        import aap_gateway_api.signals  # noqa 401

    def _is_server_startup(self):
        """
        Check if this is actual server startup (uwsgi/runserver) vs a management command.
        Management commands like showmigrations run frequently and shouldn't clear the cache.
        """
        import sys

        # Check if running under uwsgi
        try:
            import uwsgi  # noqa: F401

            return True
        except ImportError:
            pass

        # Check if running via runserver
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            return True

        return False
