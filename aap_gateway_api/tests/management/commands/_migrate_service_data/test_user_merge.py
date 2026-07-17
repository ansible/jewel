"""Tests for UserMergeMixin: comprehensive_multi_service_migration,
merge_partially_migrated_users, merge_user_group.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from ansible_base.resource_registry.models import Resource, service_id
from django.core.management import call_command

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import User
from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import kill_test_service, launch_test_service


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


# =============================================================================
# Integration test fixtures
# =============================================================================


@pytest.fixture
def comprehensive_migration_controller_service(service_api_route_controller):
    proc = launch_test_service(
        svc_route=service_api_route_controller,
        fixture="comprehensive_migration_controller",
    )
    yield service_api_route_controller
    kill_test_service(proc)


@pytest.fixture
def comprehensive_migration_hub_service(service_api_route_hub):
    proc = launch_test_service(
        svc_route=service_api_route_hub,
        fixture="comprehensive_migration_hub",
        svc_type="galaxy",
    )
    yield service_api_route_hub
    kill_test_service(proc)


@pytest.fixture
def comprehensive_migration_eda_service(service_api_route_eda):
    proc = launch_test_service(
        svc_route=service_api_route_eda,
        fixture="comprehensive_migration_eda",
        svc_type="eda",
    )
    yield service_api_route_eda
    kill_test_service(proc)


# =============================================================================
# test_comprehensive_multi_service_migration
# =============================================================================


@pytest.mark.django_db(transaction=True)
def test_comprehensive_multi_service_migration(
    comprehensive_migration_controller_service,
    comprehensive_migration_hub_service,
    comprehensive_migration_eda_service,
    admin_user,
    patched_resource_client,
    patched_load_rbac,
    capsys,
):
    """Comprehensive test for AAP-47840 multi-service user migration."""
    controller_client = patched_resource_client(service=comprehensive_migration_controller_service, user=admin_user, raise_if_bad_request=True)
    hub_client = patched_resource_client(service=comprehensive_migration_hub_service, user=admin_user, raise_if_bad_request=True)
    eda_client = patched_resource_client(service=comprehensive_migration_eda_service, user=admin_user, raise_if_bad_request=True)

    gateway_service_id = str(service_id())

    assert not User.objects.filter(username="controller-only-user").exists()
    assert not User.objects.filter(username="controller-hub-user").exists()
    assert not User.objects.filter(username="hub-eda-user").exists()
    assert not User.objects.filter(username="all-services-user").exists()

    call_command("migrate_service_data", username=admin_user.username)

    captured = capsys.readouterr()

    assert "Found 3 services to migrate" in captured.out
    assert "Merging partially migrated users" in captured.out
    assert "Successful migrations: 3" in captured.out
    assert "Failed migrations: 0" in captured.out

    # === Test Case 1: controller-only-user ===
    gateway_user_list = User.objects.filter(username__endswith="controller-only-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="controller-only-user")
    assert gateway_user.email == "controller@example.com"
    assert gateway_user.first_name == "Controller"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    gateway_resource_list = Resource.objects.filter(name__endswith="controller-only-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert hub_resource_list["count"] == 0

    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "controller-only-user"}).json()
    assert eda_resource_list["count"] == 0

    # === Test Case 2: controller-hub-user ===
    gateway_user_list = User.objects.filter(username__endswith="controller-hub-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="controller-hub-user")
    assert gateway_user.email == "multi@example.com"
    assert gateway_user.first_name == "Multi"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    gateway_resource_list = Resource.objects.filter(name__endswith="controller-hub-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "controller-hub-user"}).json()
    assert eda_resource_list["count"] == 0

    # === Test Case 3: hub-eda-user ===
    gateway_user_list = User.objects.filter(username__endswith="hub-eda-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="hub-eda-user")
    assert gateway_user.email == "hubeda@example.com"
    assert gateway_user.first_name == "HubEda"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    gateway_resource_list = Resource.objects.filter(name__endswith="hub-eda-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert controller_resource_list["count"] == 0

    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "hub-eda-user"}).json()
    assert eda_resource_list["count"] == 1
    eda_resource = eda_client.get_resource(eda_resource_list["results"][0]["ansible_id"]).json()
    assert eda_resource["ansible_id"] == gateway_resource_ansible_id
    assert eda_resource["service_id"] == gateway_service_id
    assert eda_resource["is_partially_migrated"] is False

    # === Test Case 4: all-services-user ===
    gateway_user_list = User.objects.filter(username__endswith="all-services-user")
    assert gateway_user_list.count() == 1
    gateway_user = User.objects.get(username="all-services-user")
    assert gateway_user.email == "allservices@example.com"
    assert gateway_user.first_name == "AllServices"
    assert gateway_user.last_name == "User"
    assert gateway_user.resource.is_partially_migrated is False
    assert str(gateway_user.resource.service_id) == gateway_service_id

    gateway_resource_list = Resource.objects.filter(name__endswith="all-services-user")
    assert gateway_resource_list.count() == 1
    gateway_resource = gateway_resource_list.first()
    assert str(gateway_resource.service_id) == gateway_service_id
    assert gateway_resource.is_partially_migrated is False
    gateway_resource_ansible_id = str(gateway_resource.ansible_id)

    controller_resource_list = controller_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert controller_resource_list["count"] == 1
    controller_resource = controller_client.get_resource(controller_resource_list["results"][0]["ansible_id"]).json()
    assert controller_resource["ansible_id"] == gateway_resource_ansible_id
    assert controller_resource["service_id"] == gateway_service_id
    assert controller_resource["is_partially_migrated"] is False

    hub_resource_list = hub_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert hub_resource_list["count"] == 1
    hub_resource = hub_client.get_resource(hub_resource_list["results"][0]["ansible_id"]).json()
    assert hub_resource["ansible_id"] == gateway_resource_ansible_id
    assert hub_resource["service_id"] == gateway_service_id
    assert hub_resource["is_partially_migrated"] is False

    eda_resource_list = eda_client.list_resources(filters={"name__endswith": "all-services-user"}).json()
    assert eda_resource_list["count"] == 1
    eda_resource = eda_client.get_resource(eda_resource_list["results"][0]["ansible_id"]).json()
    assert eda_resource["ansible_id"] == gateway_resource_ansible_id
    assert eda_resource["service_id"] == gateway_service_id
    assert eda_resource["is_partially_migrated"] is False

    # ==== Final validation - no partially migrated user in any service ====
    gateway_resource_list = Resource.objects.filter(content_type__resource_type__name="shared.user", is_partially_migrated=True)
    assert gateway_resource_list.count() == 0

    controller_resource_list = controller_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert controller_resource_list["count"] == 0

    hub_resource_list = hub_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert hub_resource_list["count"] == 0

    eda_resource_list = eda_client.list_resources(filters={"is_partially_migrated": True}).json()
    assert eda_resource_list["count"] == 0


# =============================================================================
# _merge_partially_migrated_users tests
# =============================================================================


@pytest.mark.django_db
def test_merge_partially_migrated_users_with_users(admin_user, capsys, service_api_route_controller):
    """Exercise the partially migrated user merge flow with actual users."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    controller_service_id = uuid.uuid4()
    service_api_route_controller.service_cluster.service_id = controller_service_id
    service_api_route_controller.service_cluster.save()

    user1 = User.objects.create(username="controller_testmerge1")
    resource1 = user1.resource
    resource1.service_id = controller_service_id
    resource1.is_partially_migrated = True
    resource1.save()

    cmd._merge_partially_migrated_users([service_api_route_controller], admin_user)

    captured = capsys.readouterr()
    assert "Grouping users by their service types" in captured.out
    assert "Correlating users across services" in captured.out
    assert "user groups to merge" in captured.out
    assert "Merging" in captured.out
    assert "Completed merging" in captured.out


# =============================================================================
# _merge_user_group tests
# =============================================================================


@pytest.mark.django_db
def test_merge_user_group_with_conflicts(capsys):
    """When users can't be merged due to conflicts, warnings are logged."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    user1 = User.objects.create(username="main_user", email="main@example.com")
    user2 = User.objects.create(username="other_user", email="other@example.com")

    user_accounts = [
        ("controller", user1, "main_user"),
        ("hub", user2, "other_user"),
    ]

    merge_patch = "aap_gateway_api.management.commands._migrate_service_data.user_merge.can_accounts_be_merged"
    with patch(merge_patch, return_value=False):
        result = cmd._merge_user_group("main_user", user_accounts)

    assert result == 0
    captured = capsys.readouterr()
    assert "Merging user group for" in captured.out
    assert "Using controller user" in captured.out
    assert "Cannot merge user group" in captured.err
    assert "conflicts detected" in captured.err


@pytest.mark.django_db
def test_merge_user_group_successful(capsys):
    """When users can be merged, the merge proceeds and logs progress."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    user1 = User.objects.create(username="main_user2")
    user2 = User.objects.create(username="other_user2")

    user_accounts = [
        ("controller", user1, "main_user2"),
        ("hub", user2, "other_user2"),
    ]

    merge_mod = "aap_gateway_api.management.commands._migrate_service_data.user_merge"
    with (
        patch(f"{merge_mod}.can_accounts_be_merged", return_value=True),
        patch(f"{merge_mod}.link_account"),
        patch(f"{merge_mod}.migrate_account"),
    ):
        result = cmd._merge_user_group("main_user2", user_accounts)

    assert result == 2
    captured = capsys.readouterr()
    assert "Merging hub user" in captured.out
    assert "Successfully merged hub user" in captured.out
    assert "Migrating main user" in captured.out
    assert "Successfully migrated main user" in captured.out


# =============================================================================
# _correlate_users_across_services tests
# =============================================================================


def test_correlate_users_strips_galaxy_prefix():
    """The galaxy_ prefix is stripped to produce the base username."""
    cmd = MigrateCommand()
    mock_user = MagicMock()
    all_users = {"hub": [("galaxy_john", mock_user)]}

    result = cmd._correlate_users_across_services(all_users)

    assert "john" in result
    assert len(result["john"]) == 1
    service_type, user_obj, original_username = result["john"][0]
    assert service_type == "hub"
    assert user_obj is mock_user
    assert original_username == "galaxy_john"


def test_correlate_users_strips_eda_prefix():
    """The eda_ prefix is stripped to produce the base username."""
    cmd = MigrateCommand()
    mock_user = MagicMock()
    all_users = {"eda": [("eda_john", mock_user)]}

    result = cmd._correlate_users_across_services(all_users)

    assert "john" in result
    assert len(result["john"]) == 1
    service_type, user_obj, original_username = result["john"][0]
    assert service_type == "eda"
    assert user_obj is mock_user
    assert original_username == "eda_john"


def test_correlate_users_no_prefix_kept_as_is():
    """A username without a known prefix is kept unchanged."""
    cmd = MigrateCommand()
    mock_user = MagicMock()
    all_users = {"controller": [("john", mock_user)]}

    result = cmd._correlate_users_across_services(all_users)

    assert "john" in result
    assert len(result["john"]) == 1
    service_type, user_obj, original_username = result["john"][0]
    assert service_type == "controller"
    assert user_obj is mock_user
    assert original_username == "john"


def test_correlate_users_groups_across_services():
    """Users from different services with the same base name are grouped together."""
    cmd = MigrateCommand()
    controller_user = MagicMock()
    hub_user = MagicMock()
    eda_user = MagicMock()
    all_users = {
        "controller": [("john", controller_user)],
        "hub": [("galaxy_john", hub_user)],
        "eda": [("eda_john", eda_user)],
    }

    result = cmd._correlate_users_across_services(all_users)

    assert "john" in result
    assert len(result["john"]) == 3
    # Verify ordering follows SERVICE_TYPE_ORDER: controller, hub, eda
    assert result["john"][0] == ("controller", controller_user, "john")
    assert result["john"][1] == ("hub", hub_user, "galaxy_john")
    assert result["john"][2] == ("eda", eda_user, "eda_john")
