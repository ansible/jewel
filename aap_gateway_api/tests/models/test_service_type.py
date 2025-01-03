import pytest

from aap_gateway_api.models import DefaultServiceType, ServiceType


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
