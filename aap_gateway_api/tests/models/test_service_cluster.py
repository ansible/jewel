import pytest

from aap_gateway_api.models import ServiceCluster


@pytest.mark.parametrize(
    "service_type,expected_path",
    [
        ('controller', '/prefix/login/'),
        ('eda', '/prefix/v1/auth/session/login/'),
        ('hub', '/auth/login'),
        ('gateway', None),
    ],
)
def test_service_cluster_login_url(service_type, expected_path):
    sc = ServiceCluster(service_type=service_type)
    assert sc.get_login_path('/prefix/') == expected_path


@pytest.mark.parametrize(
    "service_type,expected_path",
    [
        ('controller', '/prefix/logout/'),
        ('eda', '/prefix/v1/auth/session/logout/'),
        ('hub', '/auth/logout'),
        ('gateway', None),
    ],
)
def test_service_cluster_logout_url(service_type, expected_path):
    sc = ServiceCluster(service_type=service_type)
    assert sc.get_logout_path('/prefix/') == expected_path
