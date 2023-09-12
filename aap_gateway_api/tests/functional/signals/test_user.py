from unittest import mock


@mock.patch("aap_gateway_api.signals.user.logger")
def test_logout_signal_logging(logger, admin_api_client):
    admin_api_client.logout()
    assert logger.info.call_count == 1
    assert logger.info.call_args[0][0].startswith("User logged out: admin")
