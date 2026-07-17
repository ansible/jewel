import tempfile
import uuid
from io import StringIO
from unittest import mock

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster, ServiceNode

POPULATE_TARGET = "aap_gateway_api.management.commands.sync_service_ids.populate_missing_service_ids"
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


@pytest.mark.django_db
def test_username_resolves_existing_user(user, service_cluster_controller, service_api_route_controller):
    """--username resolves to a User and passes it through to populate_missing_service_ids."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    out = StringIO()
    with mock.patch(POPULATE_TARGET, return_value=([service_cluster_controller.name], [])) as mock_pop:
        call_command("sync_service_ids", username=user.username, stdout=out)

    mock_pop.assert_called_once_with(user=user, force=False)


@pytest.mark.django_db
def test_username_missing_raises_command_error():
    """--username with a non-existent user raises CommandError."""
    with pytest.raises(CommandError, match="does not exist"):
        call_command("sync_service_ids", username="ghost_user_xyz")


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


def _write_config(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f)


@pytest.mark.django_db
def test_register_creates_cluster_node_and_route(service_type_controller, service_api_route_controller):
    """--register creates ServiceCluster, ServiceNode, and ServiceAPIRoute from YAML."""
    new_id = str(uuid.uuid4())

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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    out = StringIO()
    with mock.patch(FETCH_TARGET, return_value=new_id):
        call_command("sync_service_ids", register=config_path, stdout=out)

    assert ServiceCluster.objects.filter(name="mymetrics").exists()
    assert ServiceNode.objects.filter(address="10.0.0.1").exists()
    assert ServiceAPIRoute.objects.filter(api_slug="mymetrics").exists()
    assert "mymetrics" in out.getvalue()


@pytest.mark.django_db
def test_register_existing_cluster_is_idempotent(service_cluster_controller, service_type_controller, service_api_route_controller):
    """--register does not duplicate an existing cluster; nodes are replaced."""
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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    initial_cluster_count = ServiceCluster.objects.count()

    with mock.patch(FETCH_TARGET, return_value=str(uuid.uuid4())):
        call_command("sync_service_ids", register=config_path)

    assert ServiceCluster.objects.count() == initial_cluster_count
    assert ServiceNode.objects.filter(address="10.9.9.9").exists()


@pytest.mark.django_db
def test_register_missing_file_raises_command_error():
    """--register with a non-existent file raises CommandError."""
    with pytest.raises(CommandError, match="does not exist"):
        call_command("sync_service_ids", register="/tmp/this_file_does_not_exist_xyz.yml")


@pytest.mark.django_db
def test_register_unknown_service_type_raises_command_error(service_type_controller):
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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    with pytest.raises(CommandError, match="Unknown service type"):
        call_command("sync_service_ids", register=config_path)


@pytest.mark.django_db
def test_register_invalid_yaml_raises_command_error():
    """--register with a YAML file missing the 'services' key raises CommandError."""
    config = {"not_services": {}}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    with pytest.raises(CommandError, match="must be a YAML mapping with a 'services' key"):
        call_command("sync_service_ids", register=config_path)
