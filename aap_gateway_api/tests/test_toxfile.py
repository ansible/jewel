"""Unit tests for the tox Podman plugin helpers in toxfile.py."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tox")

from tox.tox_env.errors import Fail

import toxfile
from toxfile import ExposedPort, published_port


@pytest.mark.parametrize(
    "value,environment_variable,container_port,protocol",
    [
        ("DB_PORT=5432/tcp", "DB_PORT", "5432", "tcp"),
        ("REDIS_PORT=6379/udp", "REDIS_PORT", "6379", "udp"),
    ],
)
def test_exposed_port_parses_valid_value(value, environment_variable, container_port, protocol):
    port = ExposedPort(value)
    assert port.environment_variable == environment_variable
    assert port.container_port == container_port
    assert port.protocol == protocol
    assert port.value == f"{container_port}/{protocol}"


@pytest.mark.parametrize(
    "value",
    [
        "5432/tcp",
        "db_port=5432/tcp",
        "DB_PORT=5432",
        "DB_PORT=notaport/tcp",
        "DB_PORT=5432/sctp",
    ],
)
def test_exposed_port_rejects_invalid_value(value):
    with pytest.raises(ValueError):
        ExposedPort(value)


@pytest.mark.parametrize(
    "stdout,expected",
    [
        ("0.0.0.0:32768\n", "32768"),
        ("127.0.0.1:5432", "5432"),
        ("[::]:12345\n[::1]:12345\n", "12345"),
    ],
)
def test_published_port_parses_mapping(stdout, expected):
    result = MagicMock(stdout=stdout)
    with patch.object(toxfile, "run_podman", return_value=result) as run_podman:
        assert published_port("tox-podman-db", ExposedPort("DB_PORT=5432/tcp")) == expected
        run_podman.assert_called_once_with("port", "tox-podman-db", "5432/tcp", timeout=5)


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "\n",
        "no-colon-here",
        ":",
    ],
)
def test_published_port_raises_on_invalid_output(stdout):
    result = MagicMock(stdout=stdout)
    exposed_port = ExposedPort("DB_PORT=5432/tcp")
    with patch.object(toxfile, "run_podman", return_value=result):
        with pytest.raises(Fail):
            published_port("tox-podman-db", exposed_port)
