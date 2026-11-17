from unittest.mock import Mock

import requests

from aap_gateway_api.tests.service_test_app import launch


def test_launch_service_waits_for_delayed_readiness(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.communicate.return_value = (b"", b"")
    get_response = Mock(status_code=200)
    attempts = 0

    def get_until_ready(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 21:
            raise requests.ConnectionError("service is still starting")
        return get_response

    monkeypatch.setattr(launch.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(launch.requests, "get", get_until_ready)
    monkeypatch.setattr(launch.time, "sleep", lambda _: None)

    result = launch.launch_service("awx", 10000, dev_mode=True, save_std=False)

    assert result is process
    assert attempts == 22
    process.kill.assert_not_called()


def test_launch_service_captures_child_logs_without_pipe_blocking(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    monkeypatch.setattr(launch.requests, "get", Mock(return_value=Mock(status_code=200)))

    launch.launch_service("awx", 10000, dev_mode=True, save_std=True)

    stdout_sink = popen.call_args.kwargs["stdout"]
    stderr_sink = popen.call_args.kwargs["stderr"]
    try:
        assert stdout_sink != launch.subprocess.PIPE
        assert stderr_sink != launch.subprocess.PIPE
        assert hasattr(stdout_sink, "seek")
        assert hasattr(stderr_sink, "seek")
    finally:
        if hasattr(stdout_sink, "close"):
            stdout_sink.close()
        if hasattr(stderr_sink, "close"):
            stderr_sink.close()
