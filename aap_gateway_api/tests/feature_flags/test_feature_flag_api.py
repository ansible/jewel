import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.conf import settings
from django.test import override_settings
from flags.state import flag_state
from rest_framework import status

from aap_gateway_api.settings import _set_feature_flags


def test_feature_flags_list_endpoint(admin_api_client):
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == status.HTTP_200_OK, response.data
    # Test number of feature flags.
    # Modify each time a flag is added to default settings
    assert len(response.data) == 0


@override_settings(
    FLAGS={
        "FEATURE_SOME_PLATFORM_FLAG_ENABLED": [
            {"condition": "boolean", "value": False},
            {"condition": "before date", "value": "2022-06-01T12:00Z"},
        ],
        "FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED": [
            {"condition": "boolean", "value": True},
        ],
    }
)
@pytest.mark.django_db
def test_feature_flags_override_flags(admin_api_client):
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == status.HTTP_200_OK, response.data
    assert len(response.data) == 2
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_ENABLED"] is False
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED"] is True


@override_settings(
    FLAGS={
        "FEATURE_SOME_PLATFORM_FLAG_ENABLED": [
            {"condition": "boolean", "value": False},
        ],
    },
)
@pytest.mark.django_db
def test_set_feature_flags(admin_api_client):
    _set_feature_flags(settings.FLAGS, {"FEATURE_SOME_PLATFORM_FLAG_ENABLED": True})
    assert flag_state("FEATURE_SOME_PLATFORM_FLAG_ENABLED") is True
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == status.HTTP_200_OK, response.data
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_ENABLED"] is True
