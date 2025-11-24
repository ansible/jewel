import pytest
from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.utils import create_initial_data as seed_feature_flags
from django.conf import settings


@pytest.fixture
def feature_flag_setup():
    """
    Context manager fixture for feature flag setup and cleanup.
    Sets up feature flag, yields control to test, then restores original state.
    """
    from contextlib import contextmanager

    @contextmanager
    def _setup_flag(flag_name, flag_value):
        # Store original setting if it exists
        original_value = getattr(settings, flag_name, None)

        # Clean up and recreate feature flags
        AAPFlag.objects.filter(name=flag_name).delete()
        setattr(settings, flag_name, flag_value)
        seed_feature_flags()

        try:
            yield
        finally:
            # Restore original setting after test
            if original_value is not None:
                setattr(settings, flag_name, original_value)
            elif hasattr(settings, flag_name):
                delattr(settings, flag_name)
            # Re-seed with original value
            seed_feature_flags()

    return _setup_flag


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "flag_value,expected_result",
    [
        ('True', '::'),
        ('False', '0.0.0.0'),
    ],
)
def test_ipv6_flag_on_xds_listener_config(flag_value, expected_result, http_port, feature_flag_setup):
    with feature_flag_setup("FEATURE_GATEWAY_IPV6_USAGE_ENABLED", flag_value):
        config = http_port.get_xds_listener_config()
        assert config['address']['socket_address']['address'] == expected_result
