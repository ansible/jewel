"""Tests for ResourceMigrationMixin: migrate_conflicting_user, merge_users,
correcting_user_service_id, migrating_user_with_invalid_email,
updating_resource_data_for_invalid_resource,
process_resource_page_batch_*, reconcile_existing_resource_*.
"""

from io import StringIO
from unittest.mock import Mock, patch

import pytest
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.core.management import call_command

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import MigratedUserMetadata, Organization, User
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import SEP_CHAR, assert_all_resources_synced


@pytest.mark.django_db(transaction=True)
def test_migrate_conflicting_user(migration_service, admin_user, admin_api_client, patched_resource_client, patched_load_rbac):
    assert not User.objects.filter(username="natasha").exists()
    assert not User.objects.filter(username="hawkeye").exists()

    from aap_gateway_api.models import ServiceCluster, ServiceType

    fake_service_type = ServiceType.objects.create(name="fake")
    fake_service_cluster = ServiceCluster.objects.create(name="fake", service_type=fake_service_type)

    u = User.objects.create(username="hawkeye")
    MigratedUserMetadata.objects.create(user=u, service=fake_service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)

    pre_sync_resources = service_client.list_resources(
        {
            "service_id": service_client.service.service_cluster.service_id,
            "content_type__resource_type__name": "shared.user",
            "not__name": admin_user.username,
        }
    ).json()

    assert len(pre_sync_resources['results']) > 0

    assert_all_resources_synced(admin_api_client, migration_service, service_client)

    assert User.objects.filter(username="natasha").exists()
    assert User.objects.filter(username="hawkeye").exists()

    assert not User.objects.filter(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').exists()

    hawkeye_user = User.objects.get(username="hawkeye")
    assert hawkeye_user.original_accounts.count() == 1

    updated_resource = service_client.get_resource(str(hawkeye_user.resource.ansible_id)).json()
    assert updated_resource
    assert updated_resource["is_partially_migrated"] is False

    assert not User.objects.filter(username="already_migrated").exists()

    assert hawkeye_user.resource.service_id != migration_service.service_cluster.service_id

    gateway_service_id = service_id()
    assert str(hawkeye_user.resource.service_id) == gateway_service_id


@pytest.mark.django_db(transaction=True)
def test_merge_users(migration_service, admin_user, admin_api_client, patched_resource_client, patched_load_rbac):
    from aap_gateway_api.models import ServiceCluster, ServiceType

    fake_service_type = ServiceType.objects.create(name="fake")
    fake_service_cluster = ServiceCluster.objects.create(name="fake", service_type=fake_service_type)

    u = User.objects.create(username="hawkeye", email="hawkeye@secretbase.invalid")
    MigratedUserMetadata.objects.create(user=u, service=fake_service_cluster, original_username="hawkeye")

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    call_command("migrate_service_data", username=admin_user.username)
    assert_all_resources_synced(admin_api_client, migration_service, service_client)

    assert User.objects.filter(username="hawkeye").exists()

    assert not User.objects.filter(username=f'{service_client.service.api_slug}{SEP_CHAR}hawkeye').exists()

    hawkeye_user = User.objects.get(username="hawkeye")
    assert hawkeye_user.original_accounts.count() == 1

    updated_resource = service_client.get_resource(str(hawkeye_user.resource.ansible_id)).json()
    assert updated_resource
    assert updated_resource["is_partially_migrated"] is False

    updated_user = updated_resource['resource_data']
    assert updated_user.get('username') == 'hawkeye', updated_user

    assert not User.objects.filter(username="already_migrated").exists()


@pytest.mark.django_db(transaction=True)
def test_correcting_user_service_id(migration_service, admin_user, patched_resource_client, patched_load_rbac):
    """Verify that a service user resource with the same ansible id but a differing
    service id from gateway's has its service id corrected to gateway's via migration.
    """
    call_command("migrate_service_data", username=admin_user.username)

    service_client = patched_resource_client(service=migration_service, user=admin_user, raise_if_bad_request=True)

    response = service_client.list_resources(filters={"name": "fury"})
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    service_fury_resource_data = result["results"][0]
    service_client.update_resource(
        service_fury_resource_data["ansible_id"],
        ResourceRequestBody(**{"is_partially_migrated": False}),
        partial=True,
    )

    gw_fury_resource = Resource.objects.get(name="fury")
    gw_fury_resource.service_id = service_id()
    gw_fury_resource.save(update_fields=["service_id"])

    call_command("migrate_service_data", username=admin_user.username)

    response = service_client.list_resources(filters={"name": "fury"})
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    service_fury_resource_data = result["results"][0]
    assert service_fury_resource_data["service_id"] == service_id()


@pytest.mark.django_db(transaction=True)
def test_migrating_user_with_invalid_email(migration_service_invalid_users, admin_user, patched_load_rbac):
    cmd = MigrateCommand()
    cmd.service_slug = 'controller'

    call_command(cmd, username=admin_user.username)

    users = User.objects.filter(username="bademailuser1")
    assert users is not None and users.exists()
    for u in users:
        assert u.first_name == "Badema"
        assert u.last_name == "Iluser"
        assert u.email == ""


@pytest.mark.django_db(transaction=True)
def test_updating_resource_data_for_invalid_resource(migration_service_invalid_users, patched_load_rbac, admin_user):
    from django.core.management.base import CommandError

    with patch.object(MigrateCommand, "update_resource_data") as mocked:
        mocked.return_value = None

        cmd = MigrateCommand()
        cmd.service_slug = 'controller'

        with pytest.raises(CommandError):
            call_command(cmd, username=admin_user.username)

        assert not User.objects.filter(username="invaliduser").exists()
        assert not User.objects.filter(username="bademailuser1").exists()


@pytest.mark.django_db
def test_process_resource_page_batch_raises_on_missing_resource_data():
    """Test that _process_resource_page_batch raises when resource_data is missing."""
    cmd = MigrateCommand()
    results = [{"ansible_id": "test-id-456", "name": "test"}]
    resource_context = {"type": Mock()}

    with pytest.raises(RuntimeError, match="missing 'resource_data'"):
        cmd._process_resource_page_batch(results, resource_context)


@pytest.mark.django_db
def test_process_resource_page_batch_bulk_update():
    """Test that _process_resource_page_batch calls bulk_update_resources with correct payloads."""
    import uuid

    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.upstream_service_id = str(uuid.uuid4())

    mock_client = Mock()
    mock_client.service.service_cluster.service_type.name = "awx"
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"updated": 2, "errors": []}
    mock_client.bulk_update_resources.return_value = mock_resp
    cmd.client = mock_client

    Organization.objects.create(name="BatchOrg1")

    org_resource_type = ResourceType.objects.get(name="shared.organization")
    resource_context = {
        "type": org_resource_type,
        "type_name": "shared.organization",
        "type_serializer": org_resource_type.serializer_class,
        "type_name_field": org_resource_type.get_resource_config().name_field,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }

    batch_org_id = str(uuid.uuid4())
    new_org_id = str(uuid.uuid4())
    results = [
        {
            "ansible_id": batch_org_id,
            "name": "BatchOrg1",
            "resource_type": "shared.organization",
            "resource_data": {"name": "BatchOrg1"},
        },
        {
            "ansible_id": new_org_id,
            "name": "NewOrg",
            "resource_type": "shared.organization",
            "resource_data": {"name": "NewOrg"},
        },
    ]

    count = cmd._process_resource_page_batch(results, resource_context)
    # Returns the "updated" count from the bulk response
    assert count == 2

    mock_client.bulk_update_resources.assert_called_once()
    bulk_items = mock_client.bulk_update_resources.call_args[0][0]
    assert len(bulk_items) == 2
    assert all("ansible_id" in item for item in bulk_items)
    # The first item (BatchOrg1 exists) triggers reconcile which sets ansible_id and resource_data
    merged_item = bulk_items[0]
    assert "new_ansible_id" in merged_item
    assert "resource_data" in merged_item
    # The second item (NewOrg is new) only gets new_service_id
    new_item = bulk_items[1]
    assert "new_service_id" in new_item


@pytest.mark.django_db
def test_process_resource_page_batch_with_partially_migrated():
    """Test that is_partially_migrated is included in bulk payload when set."""
    import uuid
    from unittest.mock import patch as mock_patch

    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.upstream_service_id = str(uuid.uuid4())

    mock_client = Mock()
    mock_client.service.service_cluster.service_type.name = "awx"
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"updated": 1, "errors": []}
    mock_client.bulk_update_resources.return_value = mock_resp
    cmd.client = mock_client

    org_resource_type = ResourceType.objects.get(name="shared.organization")
    resource_context = {
        "type": org_resource_type,
        "type_name": "shared.organization",
        "type_serializer": org_resource_type.serializer_class,
        "type_name_field": org_resource_type.get_resource_config().name_field,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }

    results = [
        {
            "ansible_id": str(uuid.uuid4()),
            "name": "PartialOrg",
            "resource_type": "shared.organization",
            "resource_data": {"name": "PartialOrg"},
        },
    ]

    # Mock _reconcile_existing_resource to inject is_partially_migrated
    def mock_reconcile(upstream_resource, ctx, validated_data, updated_service_resource):
        updated_service_resource["is_partially_migrated"] = True
        return True

    with mock_patch.object(cmd, "_reconcile_existing_resource", side_effect=mock_reconcile):
        count = cmd._process_resource_page_batch(results, resource_context)

    assert count == 1
    bulk_items = mock_client.bulk_update_resources.call_args[0][0]
    assert bulk_items[0]["is_partially_migrated"] is True


@pytest.mark.django_db
def test_process_resource_page_batch_graceful_on_bulk_failure():
    """Test that bulk update HTTP failure is non-fatal and returns 0 (items will be retried)."""
    import uuid

    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.upstream_service_id = str(uuid.uuid4())

    mock_client = Mock()
    mock_client.service.service_cluster.service_type.name = "awx"
    mock_resp = Mock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_client.bulk_update_resources.return_value = mock_resp
    cmd.client = mock_client

    org_resource_type = ResourceType.objects.get(name="shared.organization")
    resource_context = {
        "type": org_resource_type,
        "type_name": "shared.organization",
        "type_serializer": org_resource_type.serializer_class,
        "type_name_field": org_resource_type.get_resource_config().name_field,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }

    results = [
        {
            "ansible_id": str(uuid.uuid4()),
            "name": "RetryOrg",
            "resource_type": "shared.organization",
            "resource_data": {"name": "RetryOrg"},
        },
    ]

    # Bulk failure is non-fatal: returns 0 and logs warning (items retry next iteration)
    count = cmd._process_resource_page_batch(results, resource_context)
    assert count == 0

    # Local gateway resource was still created (will be reconciled on retry)
    assert Organization.objects.filter(name="RetryOrg").exists()


@pytest.mark.django_db
def test_process_resource_page_batch_partial_errors():
    """Test that per-item errors from bulk update are logged as warnings."""
    import uuid

    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.upstream_service_id = str(uuid.uuid4())

    mock_client = Mock()
    mock_client.service.service_cluster.service_type.name = "awx"
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "updated": 1,
        "errors": [{"ansible_id": "some-id", "error": "Resource not found."}],
    }
    mock_client.bulk_update_resources.return_value = mock_resp
    cmd.client = mock_client

    Organization.objects.create(name="PartialErrOrg")

    org_resource_type = ResourceType.objects.get(name="shared.organization")
    resource_context = {
        "type": org_resource_type,
        "type_name": "shared.organization",
        "type_serializer": org_resource_type.serializer_class,
        "type_name_field": org_resource_type.get_resource_config().name_field,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }

    results = [
        {
            "ansible_id": str(uuid.uuid4()),
            "name": "PartialErrOrg",
            "resource_type": "shared.organization",
            "resource_data": {"name": "PartialErrOrg"},
        },
        {
            "ansible_id": str(uuid.uuid4()),
            "name": "NewPartialOrg",
            "resource_type": "shared.organization",
            "resource_data": {"name": "NewPartialOrg"},
        },
    ]

    count = cmd._process_resource_page_batch(results, resource_context)
    # Only 1 updated (the other had an error on upstream side)
    assert count == 1
    # Warning was logged for the failed item
    output = cmd.stderr.getvalue()
    assert "bulk-update failed" in output


def test_build_bulk_update_item_all_fields():
    """Test that _build_bulk_update_item includes all present fields."""
    import uuid

    cmd = MigrateCommand()
    ansible_id = str(uuid.uuid4())
    new_ansible_id = uuid.uuid4()
    updated_service_resource = {
        "new_service_id": "svc-123",
        "is_partially_migrated": True,
        "ansible_id": new_ansible_id,
        "resource_data": {"username": "test"},
    }

    result = cmd._build_bulk_update_item(ansible_id, updated_service_resource)
    assert result["ansible_id"] == ansible_id
    assert result["new_service_id"] == "svc-123"
    assert result["is_partially_migrated"] is True
    assert result["new_ansible_id"] == str(new_ansible_id)
    assert result["resource_data"] == {"username": "test"}


def test_build_bulk_update_item_minimal():
    """Test that _build_bulk_update_item only includes ansible_id when no updates."""
    cmd = MigrateCommand()
    result = cmd._build_bulk_update_item("some-id", {})
    assert result == {"ansible_id": "some-id"}


@pytest.mark.django_db
def test_reconcile_existing_resource_matching_ansible_id_same_data():
    """Case 1 with matching data: logs 'Correcting service_id'."""
    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    resource_type = ResourceType.objects.get(name="shared.organization")
    org = Organization.objects.create(name="reconcile-org")
    resource = Resource.objects.get(content_type=resource_type.content_type, object_id=org.pk)
    local_data = resource_type.serializer_class(org).data

    resource_context = {
        "type": resource_type,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }
    upstream_resource = {
        "ansible_id": str(resource.ansible_id),
        "name": org.name,
        "resource_data": local_data,
    }
    updated_service_resource = {}

    result = cmd._reconcile_existing_resource(upstream_resource, resource_context, local_data, updated_service_resource)

    assert result is False
    assert "Correcting service_id" in cmd.stdout.getvalue()


@pytest.mark.django_db
def test_reconcile_existing_resource_matching_ansible_id_different_data():
    """Case 1 with different data: logs 'Updating already-merged' and overwrites resource_data."""
    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    resource_type = ResourceType.objects.get(name="shared.organization")
    org = Organization.objects.create(name="reconcile-org-diff")
    resource = Resource.objects.get(content_type=resource_type.content_type, object_id=org.pk)
    local_data = resource_type.serializer_class(org).data

    resource_context = {
        "type": resource_type,
        "unique_fields": ["name"],
        "LocalResourceModel": Organization,
    }
    upstream_resource = {
        "ansible_id": str(resource.ansible_id),
        "name": org.name,
        "resource_data": {**local_data, "description": "stale upstream copy"},
    }
    updated_service_resource = {}

    result = cmd._reconcile_existing_resource(upstream_resource, resource_context, local_data, updated_service_resource)

    assert result is False
    assert updated_service_resource["resource_data"] == local_data
    combined_output = cmd.stdout.getvalue() + cmd.stderr.getvalue()
    assert "Updating already-merged" in combined_output


def test_deserialize_and_validate_resource_data_valid():
    """When the serializer reports valid data, the validated_data dict is returned directly."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    validated = {"username": "tony", "email": "tony@stark.invalid"}
    mock_serializer_instance = Mock()
    mock_serializer_instance.is_valid.return_value = True
    mock_serializer_instance.validated_data = validated

    mock_serializer_cls = Mock(return_value=mock_serializer_instance)

    upstream_resource = {
        "ansible_id": "test-aid-001",
        "resource_type": "shared.user",
        "resource_data": {"username": "tony", "email": "tony@stark.invalid"},
    }

    result = cmd._deserialize_and_validate_resource_data(upstream_resource, mock_serializer_cls)

    assert result == validated
    mock_serializer_cls.assert_called_once_with(data=upstream_resource["resource_data"])
    mock_serializer_instance.is_valid.assert_called_once_with(raise_exception=False)


def test_deserialize_and_validate_resource_data_invalid_then_fixed():
    """When validation fails but update_resource_data returns a fix, the fixed data is returned."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    fixed_data = {"username": "baduser", "email": ""}

    mock_serializer_instance = Mock()
    mock_serializer_instance.is_valid.return_value = False
    mock_serializer_instance.errors = {"email": ["Enter a valid email address."]}
    mock_serializer_instance.data = {"username": "baduser", "email": "not-an-email"}

    mock_serializer_cls = Mock(return_value=mock_serializer_instance)

    upstream_resource = {
        "ansible_id": "test-aid-002",
        "resource_type": "shared.user",
        "resource_data": {"username": "baduser", "email": "not-an-email"},
    }

    with patch.object(MigrateCommand, "update_resource_data", return_value=fixed_data):
        result = cmd._deserialize_and_validate_resource_data(upstream_resource, mock_serializer_cls)

    assert result == fixed_data
    # The upstream_resource should have its resource_data updated to the fixed data
    assert upstream_resource["resource_data"] == fixed_data


def test_deserialize_and_validate_resource_data_invalid_unfixable():
    """When validation fails and update_resource_data returns None, RuntimeError is raised."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    mock_serializer_instance = Mock()
    mock_serializer_instance.is_valid.return_value = False
    mock_serializer_instance.errors = {"username": ["This field is required."]}
    mock_serializer_instance.data = {}

    mock_serializer_cls = Mock(return_value=mock_serializer_instance)

    upstream_resource = {
        "ansible_id": "test-aid-003",
        "resource_type": "shared.user",
        "resource_data": {},
    }

    with patch.object(MigrateCommand, "update_resource_data", return_value=None):
        with pytest.raises(RuntimeError, match="invalid, non-correctable"):
            cmd._deserialize_and_validate_resource_data(upstream_resource, mock_serializer_cls)


def test_initialize_resource_sync_payloads():
    """Payloads contain the upstream ansible_id and the gateway service_id."""
    cmd = MigrateCommand()

    upstream_resource = {
        "ansible_id": "test-aid-100",
        "resource_data": {"username": "pepper"},
    }

    with patch("aap_gateway_api.management.commands._migrate_service_data.resource_migration.service_id", return_value="gw-service-id-42"):
        creation_kwargs, service_resource = cmd._initialize_resource_sync_payloads(upstream_resource)

    assert creation_kwargs == {"ansible_id": "test-aid-100"}
    assert service_resource == {"new_service_id": "gw-service-id-42"}


def test_get_filtered_resources_excludes_system_user():
    """For shared.user resources, the system user (settings.SYSTEM_USERNAME) is excluded."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.RESOURCE_DATA_FILTERS = {"extra_fields": "resource_data"}

    system_username = "_system"
    mock_response = Mock()
    mock_response.json.return_value = {
        "count": 3,
        "results": [
            {"name": "tony", "ansible_id": "a1"},
            {"name": system_username, "ansible_id": "a2"},
            {"name": "pepper", "ansible_id": "a3"},
        ],
    }

    cmd.client = Mock()
    cmd.client.list_resources.return_value = mock_response

    with patch("aap_gateway_api.management.commands._migrate_service_data.resource_migration.settings") as mock_settings:
        mock_settings.SYSTEM_USERNAME = system_username
        results, count = cmd._get_filtered_resources({}, "shared.user")

    assert count == 3
    assert len(results) == 2
    names = [r["name"] for r in results]
    assert system_username not in names
    assert "tony" in names
    assert "pepper" in names


def test_get_filtered_resources_non_user_type():
    """For non-user resource types, no filtering is applied and all results are returned."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.RESOURCE_DATA_FILTERS = {"extra_fields": "resource_data"}

    mock_response = Mock()
    mock_response.json.return_value = {
        "count": 2,
        "results": [
            {"name": "Org1", "ansible_id": "o1"},
            {"name": "Org2", "ansible_id": "o2"},
        ],
    }

    cmd.client = Mock()
    cmd.client.list_resources.return_value = mock_response

    results, count = cmd._get_filtered_resources({}, "shared.organization")

    assert count == 2
    assert len(results) == 2
    assert results[0]["name"] == "Org1"
    assert results[1]["name"] == "Org2"


@pytest.mark.django_db
def test_send_bulk_update_network_error():
    """Network exceptions in _send_bulk_update are caught and return 0."""
    import requests as req

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    cmd.client = Mock()
    cmd.client.bulk_update_resources.side_effect = req.exceptions.ConnectionError("Connection refused")
    cmd.client.service.service_cluster.service_type.name = "awx"

    count = cmd._send_bulk_update([{"ansible_id": "test-id", "new_service_id": "svc-id"}])
    assert count == 0
    assert "network error" in cmd.stderr.getvalue()


@pytest.mark.django_db
def test_send_bulk_update_invalid_json_response():
    """Non-JSON response body in _send_bulk_update is caught and returns 0."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("No JSON object could be decoded")
    mock_resp.text = "<html>Bad Gateway</html>"

    cmd.client = Mock()
    cmd.client.bulk_update_resources.return_value = mock_resp
    cmd.client.service.service_cluster.service_type.name = "awx"

    count = cmd._send_bulk_update([{"ansible_id": "test-id", "new_service_id": "svc-id"}])
    assert count == 0
    assert "not valid JSON" in cmd.stderr.getvalue()


@pytest.mark.django_db
def test_migrate_resource_circuit_breaker():
    """Migration raises RuntimeError after consecutive zero-progress pages."""
    import uuid

    from ansible_base.resource_registry.models import ResourceType

    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd.stderr = StringIO()
    cmd.upstream_service_id = str(uuid.uuid4())
    cmd.RESOURCE_DATA_FILTERS = {"extra_fields": "resource_data"}
    cmd._progress_thresholds = {}

    org_resource_type = ResourceType.objects.get(name="shared.organization")
    cmd.resource_types_to_migrate = {
        "shared.organization": {
            "type": org_resource_type,
            "unique_fields": ["name"],
        }
    }

    mock_client = Mock()
    mock_client.service.api_slug = "controller"
    cmd.client = mock_client

    # Simulate a page that always returns items but bulk update always fails
    with patch.object(cmd, "_get_filtered_resources") as mock_get, patch.object(cmd, "_process_resource_page_batch") as mock_batch:
        mock_get.return_value = ([{"ansible_id": "a1"}], 1)
        mock_batch.return_value = 0

        with pytest.raises(RuntimeError, match="Migration stalled"):
            cmd.migrate_resource("shared.organization")
