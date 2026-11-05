from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from aap_gateway_api.context_processors import version


@pytest.mark.parametrize(
    ("html_safe", "expected"),
    [
        (False, False),
        (True, True),
    ],
)
def test_deprecation_message_html_safe_context(html_safe, expected):
    request = RequestFactory().get("/")
    request.parser_context = {
        "view": SimpleNamespace(
            deprecated=True,
            deprecated_message_html_safe=html_safe,
        ),
    }

    with patch("aap_gateway_api.context_processors.get_api_version", return_value="1.0"):
        context = version(request)

    assert context["deprecated_message_html_safe"] is expected
