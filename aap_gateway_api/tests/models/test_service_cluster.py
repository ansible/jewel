import pytest

from aap_gateway_api.models import ServiceCluster, ServiceType


@pytest.mark.parametrize(
    "service_type,expected_path",
    [
        ('controller', '/prefix/login/'),
        ('eda', '/prefix/v1/auth/session/login/'),
        ('hub', '/auth/login'),
        ('gateway', None),
    ],
)
@pytest.mark.django_db
def test_service_cluster_login_url(service_type, expected_path):
    st = ServiceType.objects.get(name=service_type)
    sc = ServiceCluster(service_type=st)
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
@pytest.mark.django_db
def test_service_cluster_logout_url(service_type, expected_path):
    st = ServiceType.objects.get(name=service_type)
    sc = ServiceCluster(service_type=st)
    assert sc.get_logout_path('/prefix/') == expected_path


@pytest.mark.parametrize("service_type,name", [('controller', 'controller'), ('hub', 'hub'), ('eda', 'eda')])
@pytest.mark.django_db
def test_get_by_type(service_type, name):
    st = ServiceType.objects.get(name=service_type)
    ServiceCluster.objects.create(name=name, service_type=st)

    sc = ServiceCluster.get_cluster_by_type(service_type=service_type)
    assert sc.name == name

    sc = ServiceCluster.get_cluster_by_type(st)
    assert sc.name == name
