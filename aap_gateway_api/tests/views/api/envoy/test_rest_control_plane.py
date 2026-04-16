"""Unit tests for Envoy REST control plane helpers (no HTTP)."""

import hashlib

import pytest

from aap_gateway_api.models.ca_certificate import CACertificate
from aap_gateway_api.utils.xds_configs import SDS_SECRET_CONFIG_NAME
from aap_gateway_api.views.api.envoy.rest_control_plane import SecretDiscoverServiceView


@pytest.fixture
def secret_view():
    return SecretDiscoverServiceView()


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
