import uuid
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from aap_gateway_api.models import ServiceCluster

FETCH_TARGET = "aap_gateway_api.utils.service_id_sync._fetch_service_id_for_route"


# ---------------------------------------------------------------------------
# Default mode
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_null_clusters_prints_nothing_to_populate(service_cluster_controller, service_api_route_controller):
    """Outputs a friendly message when no clusters have a missing service_id."""
    service_cluster_controller.service_id = uuid.uuid4()
    service_cluster_controller.save()

    out = StringIO()
    with mock.patch(FETCH_TARGET, return_value=None):
        call_command("sync_service_ids", stdout=out)

    assert "No clusters with missing service_id found" in out.getvalue()


@pytest.mark.django_db
def test_null_cluster_fetch_success(service_cluster_controller, service_api_route_controller):
    """Populated clusters are reported on stdout."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    new_id = str(uuid.uuid4())
    out, err = StringIO(), StringIO()

    with mock.patch(FETCH_TARGET, return_value=new_id):
        call_command("sync_service_ids", stdout=out, stderr=err)

    assert service_cluster_controller.name in out.getvalue()
    assert err.getvalue() == ""


@pytest.mark.django_db
def test_null_cluster_fetch_failure(service_cluster_controller, service_api_route_controller):
    """Failed clusters are reported on stderr; command still exits 0."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    out, err = StringIO(), StringIO()

    with mock.patch(FETCH_TARGET, return_value=None):
        call_command("sync_service_ids", stdout=out, stderr=err)

    assert service_cluster_controller.name in err.getvalue()
    assert out.getvalue() == ""


@pytest.mark.django_db
def test_handle_reports_both_populated_and_failed(service_cluster_controller, service_api_route_controller):
    """When some clusters succeed and some fail, both stdout and stderr are written."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    # Extra cluster with no ServiceAPIRoute so it goes straight to failed.
    extra_cluster = ServiceCluster.objects.create(
        name="extra-cluster",
        service_type=service_cluster_controller.service_type,
    )
    out, err = StringIO(), StringIO()
    try:
        with mock.patch(FETCH_TARGET, return_value=str(uuid.uuid4())):
            call_command("sync_service_ids", stdout=out, stderr=err)

        assert service_cluster_controller.name in out.getvalue()
        assert extra_cluster.name in err.getvalue()
    finally:
        extra_cluster.delete()


# ---------------------------------------------------------------------------
# --force flag
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_force_overwrites_existing_service_id(service_cluster_controller, service_api_route_controller):
    """--force re-fetches and overwrites service_id even when one is already set."""
    original_id = uuid.uuid4()
    service_cluster_controller.service_id = original_id
    service_cluster_controller.save()

    new_id = str(uuid.uuid4())
    out = StringIO()

    with mock.patch(FETCH_TARGET, return_value=new_id):
        call_command("sync_service_ids", force=True, stdout=out)

    assert service_cluster_controller.name in out.getvalue()
    service_cluster_controller.refresh_from_db()
    assert str(service_cluster_controller.service_id) == new_id


@pytest.mark.django_db
def test_force_failure_leaves_existing_id(service_cluster_controller, service_api_route_controller):
    """--force with a failed fetch leaves the original service_id intact."""
    original_id = uuid.uuid4()
    service_cluster_controller.service_id = original_id
    service_cluster_controller.save()

    err = StringIO()
    with mock.patch(FETCH_TARGET, return_value=None):
        call_command("sync_service_ids", force=True, stderr=err)

    assert service_cluster_controller.name in err.getvalue()
    service_cluster_controller.refresh_from_db()
    assert service_cluster_controller.service_id == original_id
