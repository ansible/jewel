"""Tests for the dump_xds management command."""

import json
from io import StringIO

import pytest
from django.core.management import call_command

from aap_gateway_api.utils.xds_resources import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, invalidate_xds_cache


@pytest.fixture(autouse=True)
def _clear_xds_cache():
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)
    yield
    invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS)


@pytest.mark.django_db
def test_dump_xds_outputs_all_types(full_service_hierarchy_controller):
    out = StringIO()
    call_command("dump_xds", stdout=out)
    data = json.loads(out.getvalue())
    assert set(data) == {"cds", "lds", "sds"}
    for kind in ("cds", "lds", "sds"):
        assert data[kind]["version"]
        assert isinstance(data[kind]["resources"], list)


@pytest.mark.django_db
def test_dump_xds_includes_current_resources(full_service_hierarchy_controller):
    out = StringIO()
    call_command("dump_xds", stdout=out)
    data = json.loads(out.getvalue())
    cluster_names = {r["name"] for r in data["cds"]["resources"]}
    assert full_service_hierarchy_controller.route.envoy_cluster_name in cluster_names
    listener_names = {r["name"] for r in data["lds"]["resources"]}
    assert full_service_hierarchy_controller.route.http_port.envoy_listener_name in listener_names


@pytest.mark.django_db
def test_dump_xds_type_flag_limits_output(full_service_hierarchy_controller):
    out = StringIO()
    call_command("dump_xds", "--type", "lds", stdout=out)
    data = json.loads(out.getvalue())
    assert set(data) == {"lds"}
