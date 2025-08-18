import pytest

from aap_gateway_api.models import DefaultServiceType, ServiceType
from aap_gateway_api.models.service_type import get_service_type_name, service_type_to_api_slug


@pytest.mark.parametrize(
    "service_type",
    [x.value for x in DefaultServiceType],
)
@pytest.mark.django_db
def test_default_service_types_exist(service_type):
    st = ServiceType.objects.filter(name=service_type).first()
    assert st is not None


@pytest.mark.parametrize(
    "service_type,expected_path",
    [
        (DefaultServiceType.CONTROLLER, '/logout/'),
        (DefaultServiceType.EDA, '/v1/auth/session/logout/'),
        (DefaultServiceType.HUB, '/auth/logout'),
        (DefaultServiceType.GATEWAY, None),
    ],
)
@pytest.mark.django_db
def test_default_service_clusters_logout_url(service_type, expected_path):
    st = ServiceType.objects.get(name=service_type.value)
    assert st.logout_path == expected_path


@pytest.mark.parametrize(
    "input_service_type,expected_output",
    [
        # Test legacy mappings
        ("awx", "controller"),
        ("AWX", "controller"),  # Case insensitive
        ("galaxy", "hub"),
        ("GALAXY", "hub"),  # Case insensitive
        # Test non-legacy types pass through unchanged
        ("controller", "controller"),
        ("hub", "hub"),
        ("eda", "eda"),
        ("gateway", "gateway"),
        ("unknown_service", "unknown_service"),
    ],
)
def test_get_service_type_name(input_service_type, expected_output):
    """Test get_service_type_name function normalizes legacy service types."""
    result = get_service_type_name(input_service_type)
    assert result == expected_output


@pytest.mark.parametrize(
    "input_service_type,expected_output",
    [
        # Test legacy AWX mapping only
        ("awx", "controller"),
        ("AWX", "controller"),  # Case insensitive
        # Test galaxy does NOT get mapped (this is the key difference from get_service_type_name)
        ("galaxy", "galaxy"),
        ("GALAXY", "GALAXY"),
        # Test other types pass through unchanged
        ("controller", "controller"),
        ("hub", "hub"),
        ("eda", "eda"),
        ("gateway", "gateway"),
        ("unknown_service", "unknown_service"),
    ],
)
def test_service_type_to_api_slug(input_service_type, expected_output):
    """Test service_type_to_api_slug function only maps AWX to controller."""
    result = service_type_to_api_slug(input_service_type)
    assert result == expected_output
