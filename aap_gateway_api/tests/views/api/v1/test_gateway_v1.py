import logging

import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.views.api.v1 import V1RootView

MISSING_REVERSE_LOOKUP_MSG = "had neither a -list nor -view reverse lookup method, ignoring"


def test_gateway_v1_view(unauthenticated_api_client):
    url = get_relative_url("api_gateway_v1_root_view")
    response = unauthenticated_api_client.get(url)
    assert response.status_code == 200

    # Check a few keys that should be present in the response
    keys = ("me", "ping")
    for key in keys:
        assert key in response.data.keys()


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("role_user_access", "role_user_access"),
        ("role_team_access", "role_team_access"),
        ("users", "user"),
        ("settings", "setting"),
        ("status", "status"),
        ("ping", "ping"),
    ],
)
def test_singularize_endpoint_does_not_truncate_access_suffix(endpoint, expected):
    assert V1RootView._singularize_endpoint(endpoint) == expected


def test_missing_reverse_lookup_logs_debug_not_error_for_access_endpoints(caplog):
    view = V1RootView()
    with caplog.at_level(logging.DEBUG, logger="aap.gateway.views"):
        view._find_endpoints_reverse_lookup_names(["role_user_access", "role_team_access"])

    error_messages = [record.message for record in caplog.records if record.levelno >= logging.ERROR]
    assert not any(MISSING_REVERSE_LOOKUP_MSG in message for message in error_messages)

    debug_messages = [record.message for record in caplog.records if record.levelno == logging.DEBUG]
    assert any(f"role_user_access {MISSING_REVERSE_LOOKUP_MSG}" in message for message in debug_messages)
    assert any(f"role_team_access {MISSING_REVERSE_LOOKUP_MSG}" in message for message in debug_messages)
    assert not any("role_user_acce " in message or "role_team_acce " in message for message in debug_messages)


def test_gateway_v1_view_does_not_log_missing_reverse_lookups_as_error(unauthenticated_api_client, caplog):
    url = get_relative_url("api_gateway_v1_root_view")
    with caplog.at_level(logging.ERROR, logger="aap.gateway.views"):
        response = unauthenticated_api_client.get(url)

    assert response.status_code == 200
    assert not any(MISSING_REVERSE_LOOKUP_MSG in record.message for record in caplog.records)
