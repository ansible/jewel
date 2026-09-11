"""Unit tests for Envoy REST control plane helpers (no HTTP)."""

import hashlib

import pytest
from django.urls import reverse

from aap_gateway_api.models.ca_certificate import CACertificate
from aap_gateway_api.utils.xds_configs import SDS_SECRET_CONFIG_NAME
from aap_gateway_api.views.api.envoy.rest_control_plane import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, SecretDiscoverServiceView


@pytest.fixture
def secret_view():
    return SecretDiscoverServiceView()


@pytest.mark.django_db
def test_cds_cache_hit_returns_cached_response(unauthenticated_api_client, full_service_hierarchy_controller):
    """Second CDS call returns cached response without hitting the DB."""
    from django.core.cache import cache

    url = reverse("cds")
    first = unauthenticated_api_client.post(url, data={})
    assert first.status_code == 200
    assert cache.get(XDS_CACHE_KEY_CDS) is not None
    second = unauthenticated_api_client.post(url, data={})
    assert second.status_code == 200
    assert second.data == first.data


@pytest.mark.django_db
def test_lds_cache_hit_returns_cached_response(unauthenticated_api_client, full_service_hierarchy_controller):
    """Second LDS call returns cached response without hitting the DB."""
    from django.core.cache import cache

    url = reverse("lds")
    first = unauthenticated_api_client.post(url, data={})
    assert first.status_code == 200
    assert cache.get(XDS_CACHE_KEY_LDS) is not None
    second = unauthenticated_api_client.post(url, data={})
    assert second.status_code == 200
    assert second.data == first.data


@pytest.mark.django_db
def test_sds_cache_hit_returns_cached_response(unauthenticated_api_client):
    """Second SDS call returns cached response."""
    from django.core.cache import cache

    url = reverse("sds")
    first = unauthenticated_api_client.post(url, data={})
    assert first.status_code == 200
    assert cache.get(XDS_CACHE_KEY_SDS) is not None
    second = unauthenticated_api_client.post(url, data={})
    assert second.status_code == 200
    assert second.data == first.data


@pytest.mark.django_db
def test_lds_no_gateway_cluster(unauthenticated_api_client, full_service_hierarchy_controller):
    """LDS succeeds when no GATEWAY ServiceCluster exists."""
    from aap_gateway_api.models.service_cluster import ServiceCluster
    from aap_gateway_api.models.service_type import DefaultServiceType

    ServiceCluster.objects.filter(service_type__name=DefaultServiceType.GATEWAY.value).delete()
    url = reverse("lds")
    response = unauthenticated_api_client.post(url, data={})
    assert response.status_code == 200


@pytest.mark.django_db
def test_cds_empty_response_not_cached_during_bootstrap(unauthenticated_api_client):
    """CDS does not cache empty responses during bootstrap (before routes exist)."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("cds")
    # First call with no routes in DB
    first = unauthenticated_api_client.post(url, data={})
    assert first.status_code == 200
    # Cache should be empty since there are no routes
    assert cache.get(XDS_CACHE_KEY_CDS) is None


@pytest.mark.django_db
def test_lds_empty_response_not_cached_during_bootstrap(unauthenticated_api_client):
    """LDS does not cache empty responses during bootstrap (before HTTPPorts exist)."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("lds")
    # First call with no HTTPPorts in DB
    first = unauthenticated_api_client.post(url, data={})
    assert first.status_code == 200
    # Cache should be empty since there are no ports
    assert cache.get(XDS_CACHE_KEY_LDS) is None


@pytest.mark.django_db
def test_cds_bootstrap_recovery_path(unauthenticated_api_client, full_service_hierarchy_controller):
    """CDS bootstrap → recovery: empty initially, then populated after resources created."""
    from django.core.cache import cache

    from aap_gateway_api.models import HTTPPort, Route
    from aap_gateway_api.models.service_cluster import ServiceCluster
    from aap_gateway_api.models.service_type import DefaultServiceType, ServiceType

    Route.objects.all().delete()
    cache.clear()

    url = reverse("cds")

    # Step 1: Poll with empty DB (bootstrap phase)
    empty_response = unauthenticated_api_client.post(url, data={})
    assert empty_response.status_code == 200
    assert cache.get(XDS_CACHE_KEY_CDS) is None  # Empty response NOT cached
    # Verify response is truly empty (no resources)
    assert "resources" not in empty_response.data or len(empty_response.data.get("resources", [])) == 0

    # Step 2: Create resources (operator reconciles)

    st, _ = ServiceType.objects.get_or_create(name=DefaultServiceType.CONTROLLER.value)
    sc = ServiceCluster.objects.create(name="test-cluster", service_type=st)
    http_port = HTTPPort.objects.create(name="test-port-8001", number=8001)
    Route.objects.create(
        name="test-route",
        http_port=http_port,
        service_cluster=sc,
        service_port=8888,
        gateway_path="/",
        service_path="/",
        is_service_https=False,
    )

    # Step 3: Poll again (recovery phase) — should now get non-empty response and cache it
    populated_response = unauthenticated_api_client.post(url, data={})
    assert populated_response.status_code == 200
    # Response now has resources
    assert "resources" in populated_response.data
    assert len(populated_response.data.get("resources", [])) > 0
    # Cache should now be populated
    cached = cache.get(XDS_CACHE_KEY_CDS)
    assert cached is not None
    assert cached == populated_response.data


@pytest.mark.django_db
def test_lds_bootstrap_recovery_path(unauthenticated_api_client, full_service_hierarchy_controller):
    """LDS bootstrap → recovery: empty initially, then populated after resources created."""
    from django.core.cache import cache

    from aap_gateway_api.models import HTTPPort, Route
    from aap_gateway_api.models.service_cluster import ServiceCluster
    from aap_gateway_api.models.service_type import DefaultServiceType, ServiceType

    HTTPPort.objects.all().delete()
    cache.clear()

    url = reverse("lds")

    # Step 1: Poll with empty DB (bootstrap phase)
    empty_response = unauthenticated_api_client.post(url, data={})
    assert empty_response.status_code == 200
    assert cache.get(XDS_CACHE_KEY_LDS) is None  # Empty response NOT cached
    # Verify response is truly empty (no resources)
    assert "resources" not in empty_response.data or len(empty_response.data.get("resources", [])) == 0

    # Step 2: Create resources (operator reconciles)
    st, _ = ServiceType.objects.get_or_create(name=DefaultServiceType.GATEWAY.value)
    sc = ServiceCluster.objects.create(name="test-gw-cluster", service_type=st)
    http_port = HTTPPort.objects.create(
        name="port-8000",
        number=8000,
    )

    Route.objects.create(
        name="test-gw-route",
        http_port=http_port,
        service_cluster=sc,
        service_port=8888,
        gateway_path="/",
        service_path="/",
        is_service_https=False,
    )

    # Step 3: Poll again (recovery phase) — should now get non-empty response and cache it
    populated_response = unauthenticated_api_client.post(url, data={})
    assert populated_response.status_code == 200
    # Response now has resources
    assert "resources" in populated_response.data
    assert len(populated_response.data.get("resources", [])) > 0
    # Cache should now be populated
    cached = cache.get(XDS_CACHE_KEY_LDS)
    assert cached is not None
    assert cached == populated_response.data


@pytest.mark.parametrize(
    "setup_certs",
    [
        pytest.param(lambda randname: None, id="no_ca_rows"),
        pytest.param(
            lambda randname: CACertificate.objects.create(
                name=randname("empty_pem"),
                pem_data="",
                sha256=hashlib.sha256(b"").hexdigest(),
            ),
            id="empty_pem_data",
        ),
        pytest.param(
            lambda randname: CACertificate.objects.create(
                name=randname("whitespace_pem"),
                pem_data="   \n\t  ",
                sha256=hashlib.sha256(b"   \n\t  ").hexdigest(),
            ),
            id="whitespace_only_pem",
        ),
    ],
)
@pytest.mark.django_db
def test_collect_db_ca_certs_no_usable_pem(secret_view, randname, setup_certs):
    CACertificate.objects.all().delete()
    setup_certs(randname)
    secret = secret_view._collect_db_ca_certs()
    assert secret["name"] == SDS_SECRET_CONFIG_NAME
    vc = secret["validation_context"]
    assert "trusted_ca" not in vc


@pytest.mark.django_db
def test_collect_db_ca_certs_with_pem_data(secret_view, randname):
    CACertificate.objects.all().delete()
    pem_a = "-----BEGIN CERTIFICATE-----\naaa\n-----END CERTIFICATE-----"
    pem_b = "-----BEGIN CERTIFICATE-----\nbbb\n-----END CERTIFICATE-----"
    CACertificate.objects.create(
        name=randname("ca_a"),
        pem_data=pem_a,
        sha256=hashlib.sha256(pem_a.encode()).hexdigest(),
    )
    CACertificate.objects.create(
        name=randname("ca_b"),
        pem_data=pem_b,
        sha256=hashlib.sha256(pem_b.encode()).hexdigest(),
    )
    secret = secret_view._collect_db_ca_certs()
    assert secret["validation_context"]["trusted_ca"]["inline_string"] == f"{pem_a}\n{pem_b}"


@pytest.mark.django_db
def test_collect_db_ca_certs_skips_empty_mixed_with_valid(secret_view, randname):
    CACertificate.objects.all().delete()
    pem = "-----BEGIN CERTIFICATE-----\nccc\n-----END CERTIFICATE-----"
    CACertificate.objects.create(
        name=randname("empty"),
        pem_data="",
        sha256=hashlib.sha256(b"").hexdigest(),
    )
    CACertificate.objects.create(
        name=randname("valid"),
        pem_data=pem,
        sha256=hashlib.sha256(pem.encode()).hexdigest(),
    )
    secret = secret_view._collect_db_ca_certs()
    assert secret["validation_context"]["trusted_ca"]["inline_string"] == pem
