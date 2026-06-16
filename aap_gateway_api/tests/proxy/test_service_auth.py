from unittest import mock

import pytest
from django.test import override_settings

from aap_gateway_api.proxy.service_auth import ServiceAuthHelper
from aap_gateway_api.utils.preferences import initialize_preferences


@pytest.mark.django_db
def test_get_pref_or_setting():
    with override_settings(GET_ME="value"):
        assert ServiceAuthHelper._get_pref_or_setting("GET_ME") == "value"

    initialize_preferences()
    assert ServiceAuthHelper._get_pref_or_setting("INSIGHTS_TRACKING_STATE") is True


@pytest.mark.django_db
def test_get_pref_or_setting_missing():
    assert ServiceAuthHelper._get_pref_or_setting("DOESNOTEXIST") is None


@pytest.mark.parametrize(
    "service_type,auth_type,expected_name, expected_value",
    [
        ("fake", "BASIC", "Authorization", "Basic ZHVtbXk6ZHVtbXk="),
        ("fake", "TOKEN", "Authorization", "Bearer dummy"),
    ],
)
@pytest.mark.django_db
def test_auth_header(service_type, auth_type, expected_name, expected_value):
    with mock.patch("aap_gateway_api.proxy.service_auth.ServiceAuthHelper._get_pref_or_setting", return_value="dummy"):
        (name, val) = ServiceAuthHelper.get_auth_header(service_type, auth_type)
    assert name == expected_name
    assert val == expected_value


def test_normalize_name_custom_mapping():
    original_map = ServiceAuthHelper.custom_setting_map.copy()
    try:
        ServiceAuthHelper.custom_setting_map = {"MAPPED_KEY": "CUSTOM_VALUE"}
        assert ServiceAuthHelper._normalize_name("mapped_key") == "CUSTOM_VALUE"
        assert ServiceAuthHelper._normalize_name("unmapped") == "UNMAPPED"
    finally:
        ServiceAuthHelper.custom_setting_map = original_map


@pytest.mark.parametrize(
    "service_type,auth_type",
    [
        ("fake", "BASIC"),
        ("fake", "TOKEN"),
    ],
)
@pytest.mark.django_db
def test_auth_header_no_creds(service_type, auth_type):
    with pytest.raises((NameError, RuntimeError)):
        ServiceAuthHelper.get_auth_header(service_type, auth_type)


@pytest.mark.django_db
def test_auth_header_invalid_auth_type():
    with pytest.raises(RuntimeError, match="Invalid auth_type"):
        ServiceAuthHelper.get_auth_header("fake", "INVALID")
