import logging

import pytest
from django.core.exceptions import FieldError
from django.db import IntegrityError

from aap_gateway_api.utils.preferences import PreferenceCorruptError
from aap_gateway_api.views import gateway_exception_handler


@pytest.mark.parametrize(
    "exc_class,raw_message,expected_message",
    [
        (IntegrityError, "UNIQUE constraint failed: aap_gateway_api_organization.name", "A resource with these values already exists."),
        (FieldError, "Cannot resolve keyword 'foo' into field on model 'Organization'", "Invalid field in request."),
    ],
)
def test_exception_handler_does_not_leak_db_details(exc_class, raw_message, expected_message):
    exc = exc_class(raw_message)
    response = gateway_exception_handler(exc, context={"view": None, "request": None})
    assert raw_message not in str(response.data)
    assert response.data["detail"] == expected_message


def test_exception_handler_returns_503_on_preference_corrupt_error():
    exc = PreferenceCorruptError("Preference 'proxy__jwt_private_key' has corrupt data.")
    response = gateway_exception_handler(exc, context={"view": None, "request": None})
    assert response.status_code == 503
    assert "proxy__jwt_private_key" in response.data["detail"]
    assert "corrupt" in response.data["detail"]


def test_exception_handler_does_not_catch_other_exceptions():
    exc = ValueError("some other error")
    response = gateway_exception_handler(exc, context={"view": None, "request": None})
    assert response is None, "Non-handled exceptions should pass through to DRF's default handler which returns None"


@pytest.mark.parametrize(
    "exc_class,expected_log_fragment",
    [
        (IntegrityError, "IntegrityError in API request"),
        (FieldError, "FieldError in API request"),
    ],
)
def test_exception_handler_logs_original_error(exc_class, expected_log_fragment, caplog):
    """Original exception details are logged at WARNING level for debugging."""
    raw_message = "sensitive DB details here"
    exc = exc_class(raw_message)
    with caplog.at_level(logging.WARNING, logger="aap.gateway.views"):
        gateway_exception_handler(exc, context={"view": None, "request": None})
    assert any(expected_log_fragment in record.message for record in caplog.records)
    assert any(raw_message in str(record.exc_info) for record in caplog.records)


@pytest.mark.parametrize(
    "exc_class,expected_message",
    [
        (IntegrityError, "A resource with these values already exists."),
        (FieldError, "Invalid field in request."),
    ],
)
def test_exception_handler_handles_empty_args(exc_class, expected_message):
    """Exceptions with no args don't cause IndexError."""
    exc = exc_class()
    response = gateway_exception_handler(exc, context={"view": None, "request": None})
    assert response.data["detail"] == expected_message
