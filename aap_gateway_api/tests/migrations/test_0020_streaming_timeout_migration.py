import importlib
import warnings

import django.apps
import pytest

from aap_gateway_api.models import HTTPPort, ServiceCluster, ServiceType
from aap_gateway_api.models.preference import Preference
from aap_gateway_api.models.route import Route

_migration = importlib.import_module('aap_gateway_api.migrations.0020_route_request_timeout_seconds')
migrate_streaming_timeouts_forward = _migration.migrate_streaming_timeouts_forward
migrate_streaming_timeouts_reverse = _migration.migrate_streaming_timeouts_reverse


@pytest.fixture
def lightspeed_route(db):
    """Create a lightspeed service type, cluster, port, and route."""
    service_type, _ = ServiceType.objects.get_or_create(name='lightspeed')
    cluster, _ = ServiceCluster.objects.get_or_create(name='lightspeed', service_type=service_type)
    port, _ = HTTPPort.objects.get_or_create(name='test-migration-port', defaults={'number': 9999})
    route = Route.objects.create(
        name='lightspeed-api-route',
        http_port=port,
        service_cluster=cluster,
        service_port=8080,
        is_service_https=False,
        service_path='/api/',
        gateway_path='/api/lightspeed/',
    )
    yield route
    route.delete()


def _create_pref(name, raw_value):
    """Insert a preference row directly, bypassing Preference.save() which chokes on unregistered prefs."""
    pref = Preference(section='proxy', name=name, raw_value=str(raw_value))
    Preference.objects.bulk_create([pref])
    return pref


def _run_forward():
    migrate_streaming_timeouts_forward(django.apps.apps, None)


def _run_reverse():
    migrate_streaming_timeouts_reverse(django.apps.apps, None)


class TestMigrateStreamingTimeoutsForward:
    """Tests for the 0020 data migration that moves streaming preferences into route fields."""

    @pytest.mark.parametrize(
        "max_stream_duration, stream_idle_timeout",
        [
            (3600, 60),
            (7200, 120),
            (1, 1),
        ],
        ids=["defaults", "custom", "below-defaults"],
    )
    @pytest.mark.django_db
    def test_preference_values_copied_to_lightspeed_routes(
        self, lightspeed_route, max_stream_duration, stream_idle_timeout
    ):
        _create_pref('max_stream_duration', max_stream_duration)
        _create_pref('stream_idle_timeout', stream_idle_timeout)

        _run_forward()

        lightspeed_route.refresh_from_db()
        assert lightspeed_route.request_timeout_seconds == max_stream_duration
        assert lightspeed_route.idle_timeout_seconds == stream_idle_timeout

    @pytest.mark.django_db
    def test_deletes_old_preferences(self, lightspeed_route):
        _create_pref('max_stream_duration', 3600)
        _create_pref('stream_idle_timeout', 60)

        _run_forward()

        assert not Preference.objects.filter(section='proxy', name='max_stream_duration').exists()
        assert not Preference.objects.filter(section='proxy', name='stream_idle_timeout').exists()

    @pytest.mark.django_db
    def test_no_prefs_uses_old_defaults(self, lightspeed_route):
        """When neither preference exists, lightspeed routes still get the old registered defaults."""
        _run_forward()

        lightspeed_route.refresh_from_db()
        assert lightspeed_route.request_timeout_seconds == 3600
        assert lightspeed_route.idle_timeout_seconds == 60

    @pytest.mark.parametrize(
        "present_name, present_value, expected_timeout, expected_idle",
        [
            ('max_stream_duration', 9000, 9000, 60),
            ('stream_idle_timeout', 300, 3600, 300),
        ],
        ids=["only-max-stream-duration", "only-stream-idle-timeout"],
    )
    @pytest.mark.django_db
    def test_partial_prefs_uses_default_for_missing(
        self, lightspeed_route, present_name, present_value, expected_timeout, expected_idle
    ):
        _create_pref(present_name, present_value)

        _run_forward()

        lightspeed_route.refresh_from_db()
        assert lightspeed_route.request_timeout_seconds == expected_timeout
        assert lightspeed_route.idle_timeout_seconds == expected_idle

    @pytest.mark.django_db
    def test_does_not_affect_non_lightspeed_routes(self):
        """Non-lightspeed routes are not touched by the migration."""
        service_type, _ = ServiceType.objects.get_or_create(name='eda')
        cluster, _ = ServiceCluster.objects.get_or_create(name='eda', service_type=service_type)
        port, _ = HTTPPort.objects.get_or_create(name='test-migration-port', defaults={'number': 9999})
        eda_route = Route.objects.create(
            name='eda-api-route',
            http_port=port,
            service_cluster=cluster,
            service_port=8080,
            is_service_https=False,
            service_path='/api/',
            gateway_path='/api/eda/',
        )
        _create_pref('max_stream_duration', 3600)
        _create_pref('stream_idle_timeout', 60)

        _run_forward()

        eda_route.refresh_from_db()
        assert eda_route.request_timeout_seconds is None
        assert eda_route.idle_timeout_seconds is None

    @pytest.mark.django_db
    def test_no_lightspeed_routes_still_deletes_prefs(self):
        """Even without lightspeed routes, old preferences are cleaned up."""
        _create_pref('max_stream_duration', 3600)
        _create_pref('stream_idle_timeout', 60)

        _run_forward()

        assert not Preference.objects.filter(section='proxy', name='max_stream_duration').exists()
        assert not Preference.objects.filter(section='proxy', name='stream_idle_timeout').exists()


class TestMigrateStreamingTimeoutsReverse:
    """Tests for the 0020 reverse migration warning."""

    @pytest.mark.django_db
    def test_reverse_emits_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _run_reverse()

        assert len(caught) == 1
        assert "will not restore any custom values" in str(caught[0].message)
        assert "max_stream_duration" in str(caught[0].message)
        assert "stream_idle_timeout" in str(caught[0].message)
