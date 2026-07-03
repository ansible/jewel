"""Tests for LegacyAuthenticatorsMixin: delete_legacy_authenticators and related tests."""

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from django.db import IntegrityError

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand
from aap_gateway_api.models import User


@pytest.fixture(autouse=True)
def reset_migration_flag():
    """Ensure the MigrateServiceDataHasRan flag is False before each test."""
    from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan

    MigrateServiceDataHasRan.mark_migration_not_completed()


@pytest.mark.django_db(transaction=True)
def test_duplicate_email_on_same_authenticator_should_fail(admin_user, admin_api_client, local_authenticator):
    """Test that two users cannot have the same email address on the same authenticator.

    Steps to recreate the issue:
    1. Create two users: user1, user2
    2. Create an authenticator
    3. Assign the authenticator to user1 with email address foo@test.com
    4. Assign the authenticator to user2 with email address foo@test.com

    Expected behavior: The second assignment should return an error
    """
    user1 = User.objects.create(username="user1", email="user1@example.com")
    user2 = User.objects.create(username="user2", email="user2@example.com")

    AuthenticatorUser.objects.create(user=user1, provider=local_authenticator, email="foo@test.com")

    with pytest.raises((IntegrityError, Exception)) as exc_info:
        AuthenticatorUser.objects.create(user=user2, provider=local_authenticator, email="foo@test.com")

    error_message = str(exc_info.value).lower()
    assert any(keyword in error_message for keyword in ["duplicate", "unique", "constraint", "already exists"]), (
        f"Expected error message to indicate constraint violation, got: {exc_info.value}"
    )

    assert AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com").count() == 1
    assert AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com", user=user1).exists()
    assert not AuthenticatorUser.objects.filter(provider=local_authenticator, email="foo@test.com", user=user2).exists()


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_no_legacy_authenticators(admin_user, capsys):
    """Test delete when no legacy authenticators exist"""
    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    captured = capsys.readouterr()
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_password' found" in captured.out
    assert "No legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_external_password' found" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_with_controller_admin(admin_user, capsys):
    """Test delete of controller admin authenticators"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    legacy_auth = Authenticator.objects.create(
        name="Legacy Controller Admin",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin")
    legacy_auth.refresh_from_db()

    user1 = User.objects.create(username="test_user1")
    user2 = User.objects.create(username="test_user2")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth, uid="test_user1")
    AuthenticatorUser.objects.create(user=user2, provider=legacy_auth, uid="test_user2")

    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 2
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 1

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' to clean up" in captured.out
    assert "Unlinking 2 users from legacy authenticator 'Legacy Controller Admin'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Controller Admin'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_multiple_types(admin_user, capsys):
    """Test delete of multiple legacy authenticator types"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    legacy_auth1 = Authenticator.objects.create(
        name="Legacy SSO",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth1.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth1.refresh_from_db()

    legacy_auth2 = Authenticator.objects.create(
        name="Legacy Password",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth2.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_password")
    legacy_auth2.refresh_from_db()

    legacy_auth3 = Authenticator.objects.create(
        name="Legacy External Password",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth3.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_external_password")
    legacy_auth3.refresh_from_db()

    user1 = User.objects.create(username="sso_user")
    user2 = User.objects.create(username="password_user")
    user3 = User.objects.create(username="external_user")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth1, uid="sso_user")
    AuthenticatorUser.objects.create(user=user2, provider=legacy_auth2, uid="password_user")
    AuthenticatorUser.objects.create(user=user3, provider=legacy_auth3, uid="external_user")

    assert AuthenticatorUser.objects.count() == 3
    assert Authenticator.objects.filter(type__startswith="aap_gateway_api.authentication.authenticator_plugins.legacy").count() == 3

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    assert AuthenticatorUser.objects.count() == 0
    assert Authenticator.objects.filter(type__startswith="aap_gateway_api.authentication.authenticator_plugins.legacy").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy SSO'" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy Password'" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy External Password'" in captured.out
    assert "Deleting legacy authenticator 'Legacy SSO'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Password'" in captured.out
    assert "Deleting legacy authenticator 'Legacy External Password'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_no_users(admin_user, capsys):
    """Test delete of legacy authenticators with no associated users"""
    from ansible_base.authentication.models import Authenticator

    legacy_auth = Authenticator.objects.create(
        name="Unused Legacy Auth",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth.refresh_from_db()

    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 1

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 0

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' to clean up" in captured.out
    assert "Unlinking" not in captured.out
    assert "Deleting legacy authenticator 'Unused Legacy Auth'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_preserves_non_legacy(admin_user, capsys):
    """Test that delete only unlinks users from legacy authenticators and preserves non-legacy ones"""
    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    legacy_auth = Authenticator.objects.create(
        name="Legacy Auth",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso")
    legacy_auth.refresh_from_db()

    non_legacy_auth = Authenticator.objects.create(
        name="Modern Auth",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )

    user1 = User.objects.create(username="legacy_user")
    user2 = User.objects.create(username="modern_user")

    AuthenticatorUser.objects.create(user=user1, provider=legacy_auth, uid="legacy_user")
    AuthenticatorUser.objects.create(user=user2, provider=non_legacy_auth, uid="modern_user")

    assert AuthenticatorUser.objects.count() == 2
    assert Authenticator.objects.count() == 2

    cmd = MigrateCommand()
    cmd.delete_legacy_authenticators()

    assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
    assert AuthenticatorUser.objects.filter(provider=non_legacy_auth).count() == 1
    assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.legacy_sso").count() == 0
    assert Authenticator.objects.filter(type="ansible_base.authentication.authenticator_plugins.ldap").count() == 1

    captured = capsys.readouterr()
    assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.legacy_sso' to clean up" in captured.out
    assert "Unlinking 1 users from legacy authenticator 'Legacy Auth'" in captured.out
    assert "Deleting legacy authenticator 'Legacy Auth'" in captured.out


@pytest.mark.django_db(transaction=True)
def test_delete_legacy_authenticators_integration_with_migration(admin_user, capsys, service_api_route_controller, patched_resource_client):
    """Test that legacy authenticator delete is called during migration"""
    import uuid
    from unittest.mock import Mock, patch

    from ansible_base.authentication.models import Authenticator, AuthenticatorUser

    from aap_gateway_api.tests.management.commands._migrate_service_data.conftest import setup_empty_assignment_mocks

    legacy_auth = Authenticator.objects.create(
        name="Legacy Controller Admin",
        type="ansible_base.authentication.authenticator_plugins.ldap",
        enabled=True,
        configuration={},
    )
    Authenticator.objects.filter(id=legacy_auth.id).update(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin")
    legacy_auth.refresh_from_db()

    user = User.objects.create(username="legacy_user")
    AuthenticatorUser.objects.create(user=user, provider=legacy_auth, uid="legacy_user")

    from django.core.management import call_command

    with (
        patch('aap_gateway_api.utils.resources_client.GWResourceAPIClient') as mock_client_class,
        patch('aap_gateway_api.utils.jwt_token.create_signed_jwt') as mock_jwt,
        patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key') as mock_key,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command._ensure_superuser_consistency') as mock_consistency_check,
        patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'),
    ):
        mock_jwt.return_value = 'fake-jwt-token'
        mock_key.return_value = 'fake-key'
        mock_consistency_check.return_value = None

        mock_client = Mock()
        mock_client.service = service_api_route_controller
        mock_client.user = admin_user
        mock_client.get_service_metadata.return_value.json.return_value = {
            "service_id": str(uuid.uuid4()),
            "service_type": "controller",
        }
        mock_client.list_resources.return_value.json.return_value = {
            "count": 0,
            "results": [],
        }
        setup_empty_assignment_mocks(mock_client)
        mock_client_class.return_value = mock_client

        call_command("migrate_service_data", username=admin_user.username)

        assert AuthenticatorUser.objects.filter(provider=legacy_auth).count() == 0
        assert Authenticator.objects.filter(type="aap_gateway_api.authentication.authenticator_plugins.controller_admin").count() == 0

        captured = capsys.readouterr()
        assert "Found 1 legacy authenticators of type 'aap_gateway_api.authentication.authenticator_plugins.controller_admin' to clean up" in captured.out
        assert "Unlinking 1 users from legacy authenticator 'Legacy Controller Admin'" in captured.out
        assert "Deleting legacy authenticator 'Legacy Controller Admin'" in captured.out
