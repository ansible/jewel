import pytest
from django.http.request import HttpRequest

from aap_gateway_api.utils.requests import check_csrf_origin, from_proxy


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, False),
        ({"HTTP_X_TRUSTED_PROXY": "anything"}, True),
    ],
)
def test_from_proxy(headers, expected):
    request = HttpRequest()
    for header in headers:
        request.META[header] = headers[header]

    assert from_proxy(request) == expected


@pytest.mark.parametrize(
    "input,message",
    [
        ("https://localhost", None),
        ("localhost", "The scheme must be https or http only"),
        ("https://localhost/path", "The url path needs to be empty"),
        ("https://", "The network location should not be empty"),
        ("*", None),
        ("https://*.example.com", None),
        (1, "Unable to parse this as an url"),
    ],
)
def test_check_csrf_origin(input, message):
    results = check_csrf_origin(input)
    if message is None:
        assert results == message
    else:
        assert message in results
