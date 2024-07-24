import pytest
from django.http.request import HttpRequest

from aap_gateway_api.utils.requests import from_proxy


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
