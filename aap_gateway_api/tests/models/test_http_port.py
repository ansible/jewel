import pytest


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_value,expected_result",
    [
        ('True', '::'),
        ('False', '0.0.0.0'),
    ],
)
def test_ipv6_flag_on_xds_listener_config(flag_value, expected_result, http_port, settings_override_mutable, settings):
    with settings_override_mutable('FLAGS'):
        settings.FLAGS['FEATURE_GATEWAY_IPV6_USAGE_ENABLED'][0]['value'] = flag_value
        config = http_port.get_xds_listener_config()
        assert config['address']['socket_address']['address'] == expected_result
