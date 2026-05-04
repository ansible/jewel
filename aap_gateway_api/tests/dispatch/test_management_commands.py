from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherd.run_dispatcherd_service")
@mock.patch("aap_gateway_api.management.commands.dispatcherd.dispatcherd_setup")
def test_dispatcherd_command_calls_run_service(mock_setup, mock_run_service):
    out = StringIO()
    call_command("dispatcherd", stdout=out)

    mock_setup.assert_called_once()
    mock_run_service.assert_called_once()
    assert "Starting dispatcherd service" in out.getvalue()


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherd.run_dispatcherd_service")
@mock.patch("aap_gateway_api.management.commands.dispatcherd.dispatcherd_setup")
def test_dispatcherd_command_passes_config(mock_setup, mock_run_service):
    call_command("dispatcherd")

    config = mock_setup.call_args[0][0]
    assert config["version"] == 2
    assert "pg_notify" in config["brokers"]


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherd.run_dispatcherd_service", side_effect=KeyboardInterrupt)
@mock.patch("aap_gateway_api.management.commands.dispatcherd.dispatcherd_setup")
def test_dispatcherd_command_handles_keyboard_interrupt(mock_setup, mock_run_service):
    out = StringIO()
    call_command("dispatcherd", stdout=out)

    assert "shutdown" in out.getvalue().lower()


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherd.run_dispatcherd_service")
@mock.patch("aap_gateway_api.management.commands.dispatcherd.dispatcherd_setup")
def test_dispatcherd_command_verbosity_zero_suppresses_output(mock_setup, mock_run_service):
    out = StringIO()
    call_command("dispatcherd", verbosity=0, stdout=out)

    assert out.getvalue() == ""


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherctl.get_control_from_settings")
@mock.patch("aap_gateway_api.management.commands.dispatcherctl.dispatcherd_setup")
def test_dispatcherctl_alive_command(mock_setup, mock_get_control):
    mock_ctl = mock.MagicMock()
    mock_ctl.control_with_reply.return_value = [{"alive": True}]
    mock_get_control.return_value = mock_ctl

    out = StringIO()
    call_command("dispatcherctl", "alive", stdout=out)

    mock_setup.assert_called_once()
    mock_ctl.control_with_reply.assert_called_once()
    assert "alive" in out.getvalue()


@pytest.mark.django_db
@mock.patch("aap_gateway_api.management.commands.dispatcherctl.get_control_from_settings")
@mock.patch("aap_gateway_api.management.commands.dispatcherctl.dispatcherd_setup")
def test_dispatcherctl_fewer_replies_raises_error(mock_setup, mock_get_control):
    mock_ctl = mock.MagicMock()
    mock_ctl.control_with_reply.return_value = []
    mock_get_control.return_value = mock_ctl

    with pytest.raises(CommandError, match="fewer replies"):
        call_command("dispatcherctl", "alive")


@pytest.mark.django_db
def test_dispatcherctl_no_subcommand_raises_error():
    with pytest.raises((CommandError, SystemExit)):
        call_command("dispatcherctl")
