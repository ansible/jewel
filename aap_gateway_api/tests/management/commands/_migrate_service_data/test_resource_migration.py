"""Tests for ResourceMigrationMixin: migrate_conflicting_user, merge_users,
correcting_user_service_id, migrating_user_with_invalid_email,
updating_resource_data_for_invalid_resource, use_given_name_*,
process_migrate_resource_item_*, reconcile_existing_resource_*.
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
def test_use_given_name_first_found(cmd):
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser'

    User.objects.create(username='bob')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser'


@pytest.mark.django_db
def test_use_given_name_iteration(cmd):
    User.objects.create(username='controller_foouser')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser1'

    User.objects.create(username='controller_foouser1')
    User.objects.create(username='controller_foouser2')
    assert cmd.get_new_resource_name('foouser', {'username': 'bob'}, User, 'username', 'controller') == 'controller_foouser3'


@pytest.mark.django_db
def test_process_migrate_resource_item_raises_on_missing_resource_data():
    """Test that _process_and_migrate_resource_item raises when resource_data is missing."""
    cmd = MigrateCommand()
    resource_item = {"ansible_id": "test-id-123", "name": "test"}
    resource_context = {"type": Mock()}

    with pytest.raises(RuntimeError, match="missing 'resource_data'"):
        cmd._process_and_migrate_resource_item(resource_item, resource_context)


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
