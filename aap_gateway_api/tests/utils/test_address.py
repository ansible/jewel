import pytest

from aap_gateway_api.utils.address import (
    classify_address_string,
    is_hostname_address_string,
    is_ipv4_address_string,
    is_ipv6_address_string,
)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1", "ipv4"),
        ("10.0.1.1", "ipv4"),
        ("::1", "ipv6"),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", "ipv6"),
        ("localhost", "hostname"),
        ("a-host-name", "hostname"),
    ],
)
def test_classify_address(address, expected):
    assert classify_address_string(address) == expected


@pytest.mark.parametrize(
    "address",
    [
        "localhost",
        "a-host-name",
    ],
)
def test_is_hostname_address(address):
    assert is_hostname_address_string(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.1.1",
    ],
)
def test_is_ipv4_address(address):
    assert is_ipv4_address_string(address)


@pytest.mark.parametrize(
    "address",
    [
        "::1",
        "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8",
    ],
)
def test_is_ipv6_address(address):
    assert is_ipv6_address_string(address)
