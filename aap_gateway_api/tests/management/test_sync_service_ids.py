import uuid
from io import StringIO
from unittest import mock

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster, ServiceNode

FETCH_TARGET = "aap_gateway_api.utils.service_id_sync._fetch_service_id_for_route"


# ---------------------------------------------------------------------------
# Default mode (no --register)
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
    """Failed clusters are reported on stderr."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    out, err = StringIO(), StringIO()

    with mock.patch(FETCH_TARGET, return_value=None):
        call_command("sync_service_ids", stdout=out, stderr=err)

    assert service_cluster_controller.name in err.getvalue()
    assert out.getvalue() == ""


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


# ---------------------------------------------------------------------------
# --register flag
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_register_creates_cluster_node_and_route(service_type_controller, service_api_route_controller, tmp_path):
    """--register creates ServiceCluster, ServiceNode, and ServiceAPIRoute from YAML."""
    config = {
        "services": {
            "mymetrics": {
                "type": service_type_controller.name,
                "api_slug": "mymetrics",
                "service_port": 9000,
                "service_path": "/v1/service-index/",
                "is_service_https": False,
                "nodes": [{"address": "10.0.0.1"}],
            }
        }
    }

    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    out = StringIO()
    # Return a fresh UUID per call so multiple null-id clusters don't collide on the unique constraint.
    with mock.patch(FETCH_TARGET, side_effect=lambda *a, **kw: str(uuid.uuid4())):
        call_command("sync_service_ids", register=str(config_path), stdout=out)

    assert ServiceCluster.objects.filter(name="mymetrics").exists()
    assert ServiceNode.objects.filter(address="10.0.0.1").exists()
    assert ServiceAPIRoute.objects.filter(api_slug="mymetrics").exists()
    assert "mymetrics" in out.getvalue()


@pytest.mark.django_db
def test_register_existing_cluster_is_idempotent(service_cluster_controller, service_type_controller, service_api_route_controller, tmp_path):
    """--register does not duplicate an existing cluster; new nodes are added, removed ones deleted."""
    config = {
        "services": {
            service_cluster_controller.name: {
                "type": service_type_controller.name,
                "api_slug": service_api_route_controller.api_slug,
                "service_port": service_api_route_controller.service_port,
                "service_path": service_api_route_controller.service_path,
                "is_service_https": False,
                "nodes": [{"address": "10.9.9.9"}],
            }
        }
    }

    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    initial_cluster_count = ServiceCluster.objects.count()

    with mock.patch(FETCH_TARGET, return_value=str(uuid.uuid4())):
        call_command("sync_service_ids", register=str(config_path))

    assert ServiceCluster.objects.count() == initial_cluster_count
    assert ServiceNode.objects.filter(address="10.9.9.9").exists()


@pytest.mark.django_db
def test_register_missing_file_raises_command_error():
    """--register with a non-existent file raises CommandError."""
    with pytest.raises(CommandError, match="does not exist"):
        call_command("sync_service_ids", register="/tmp/this_file_does_not_exist_xyz.yml")


@pytest.mark.django_db
def test_register_unknown_service_type_raises_command_error(service_type_controller, tmp_path):
    """--register with an unknown service type raises CommandError."""
    config = {
        "services": {
            "bad": {
                "type": "nonexistent_type",
                "api_slug": "bad",
                "service_port": 9000,
                "service_path": "/",
                "nodes": [],
            }
        }
    }

    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    register = str(config_path)
    with pytest.raises(CommandError, match="Unknown service type"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_register_invalid_yaml_raises_command_error(tmp_path):
    """--register with a YAML file missing the 'services' key raises CommandError."""
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump({"not_services": {}}))

    register = str(config_path)
    with pytest.raises(CommandError, match="must be a YAML mapping with a 'services' key"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_register_yaml_parse_error_raises_command_error(tmp_path):
    """--register with a syntactically broken YAML file raises CommandError."""
    config_path = tmp_path / "services.yml"
    config_path.write_text("key: [unclosed bracket")

    register = str(config_path)
    with pytest.raises(CommandError, match="is not valid YAML"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_validate_config_services_not_a_mapping(tmp_path):
    """--register raises CommandError when 'services' is a list instead of a mapping."""
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump({"services": ["a", "b"]}))

    register = str(config_path)
    with pytest.raises(CommandError, match="'services' must be a mapping"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_validate_config_entry_not_a_mapping(tmp_path):
    """--register raises CommandError when a service entry value is not a mapping."""
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump({"services": {"myservice": "just a string"}}))

    register = str(config_path)
    with pytest.raises(CommandError, match="must be a mapping"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_validate_config_missing_required_fields(tmp_path):
    """--register raises CommandError when required fields are absent from a service entry."""
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump({"services": {"bad": {"type": "controller"}}}))

    register = str(config_path)
    with pytest.raises(CommandError, match="missing required fields"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_validate_config_invalid_service_port(service_type_controller, tmp_path):
    """--register raises CommandError when service_port is not convertible to an integer."""
    config = {
        "services": {
            "svc": {
                "type": service_type_controller.name,
                "api_slug": "svc",
                "service_port": "not-a-number",
                "service_path": "/",
                "nodes": [],
            }
        }
    }
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    register = str(config_path)
    with pytest.raises(CommandError, match="service_port must be an integer"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_validate_config_node_missing_address(service_type_controller, tmp_path):
    """--register raises CommandError when a node entry lacks an 'address' key."""
    config = {
        "services": {
            "svc": {
                "type": service_type_controller.name,
                "api_slug": "svc",
                "service_port": 9000,
                "service_path": "/",
                "nodes": [{"not_address": "10.0.0.1"}],
            }
        }
    }
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    register = str(config_path)
    with pytest.raises(CommandError, match="must have an 'address' key"):
        call_command("sync_service_ids", register=register)


@pytest.mark.django_db
def test_handle_reports_both_populated_and_failed(service_cluster_controller, service_api_route_controller):
    """When some clusters succeed and some fail, both stdout and stderr are written."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    out, err = StringIO(), StringIO()
    # First call (controller cluster) returns a valid id; any subsequent call returns None.
    call_count = [0]

    def side_effect(*a, **kw):
        call_count[0] += 1
        return str(uuid.uuid4()) if call_count[0] == 1 else None

    # Create a second cluster with no route so it ends up in failed.
    extra_cluster = ServiceCluster.objects.create(
        name="extra-cluster",
        service_type=service_cluster_controller.service_type,
    )
    try:
        with mock.patch(FETCH_TARGET, side_effect=side_effect):
            call_command("sync_service_ids", stdout=out, stderr=err)

        assert service_cluster_controller.name in out.getvalue()
        assert extra_cluster.name in err.getvalue()
    finally:
        extra_cluster.delete()


@pytest.mark.django_db
def test_apply_services_updates_service_type_on_existing_cluster(
    service_cluster_controller, service_type_controller, service_type_hub, service_api_route_controller, tmp_path
):
    """--register updates service_type on an existing cluster when the type has changed."""
    assert service_cluster_controller.service_type == service_type_controller

    config = {
        "services": {
            service_cluster_controller.name: {
                "type": service_type_hub.name,
                "api_slug": service_api_route_controller.api_slug,
                "service_port": service_api_route_controller.service_port,
                "service_path": service_api_route_controller.service_path,
                "nodes": [],
            }
        }
    }
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    with mock.patch(FETCH_TARGET, return_value=str(uuid.uuid4())):
        call_command("sync_service_ids", register=str(config_path))

    service_cluster_controller.refresh_from_db()
    assert service_cluster_controller.service_type == service_type_hub


@pytest.mark.django_db
def test_sync_nodes_deletes_removed_and_skips_existing(service_cluster_controller, service_type_controller, service_api_route_controller, tmp_path):
    """_sync_nodes removes addresses absent from config and does not duplicate existing ones."""
    # Pre-create two nodes: one that should be kept, one that should be removed.
    ServiceNode.objects.create(
        name="keep-node",
        service_cluster=service_cluster_controller,
        address="10.0.0.1",
    )
    ServiceNode.objects.create(
        name="remove-node",
        service_cluster=service_cluster_controller,
        address="10.0.0.2",
    )

    config = {
        "services": {
            service_cluster_controller.name: {
                "type": service_type_controller.name,
                "api_slug": service_api_route_controller.api_slug,
                "service_port": service_api_route_controller.service_port,
                "service_path": service_api_route_controller.service_path,
                "nodes": [{"address": "10.0.0.1"}],  # keep "10.0.0.1", drop "10.0.0.2"
            }
        }
    }
    config_path = tmp_path / "services.yml"
    config_path.write_text(yaml.dump(config))

    with mock.patch(FETCH_TARGET, return_value=str(uuid.uuid4())):
        call_command("sync_service_ids", register=str(config_path))

    addresses = set(ServiceNode.objects.filter(service_cluster=service_cluster_controller).values_list("address", flat=True))
    assert addresses == {"10.0.0.1"}  # removed "10.0.0.2", kept "10.0.0.1" without duplication
