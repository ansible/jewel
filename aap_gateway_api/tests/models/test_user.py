import pytest
from django.test import override_settings

from aap_gateway_api.models import User


@pytest.mark.django_db
class TestUserDeletion:
    """Test cases for User model deletion functionality"""

    @pytest.mark.parametrize(
        "username,email,password,system_username_setting,is_system_user,test_description",
        [
            # Regular user deletion tests (system username not set)
            ("testuser", "test@example.com", "testpass123", None, False, "regular user with password, no system username"),
            ("user2", "user2@example.com", "password456", None, False, "regular user with password, no system username"),
            ("normaluser", "normal@example.com", None, None, False, "regular user without password, no system username"),
            ("user_with_underscore", "underscore@example.com", "pass789", None, False, "regular user with underscore, no system username"),
            ("testuser1", "test1@example.com", None, "", False, "regular user with empty system username setting"),
            ("anyuser", "any@example.com", None, "", False, "regular user with empty system username setting"),
            # System user deletion tests (should fail)
            ("_system_test", "system@example.com", None, "_system_test", True, "system user deletion should fail"),
            ("admin_test", "admin@example.com", None, "admin_test", True, "admin system user deletion should fail"),
            ("root_test", "root@example.com", None, "root_test", True, "root system user deletion should fail"),
            ("service_test", "service@example.com", None, "service_test", True, "service system user deletion should fail"),
            ("system123", "system123@example.com", None, "system123", True, "numeric system user deletion should fail"),
            # Regular users when system username is set (should succeed)
            ("regularuser1", "regular1@example.com", None, "admin_test_1", False, "regular user when system username set"),
            ("normaluser", "normal@example.com", None, "system_test_1", False, "normal user when system username set"),
            ("testuser", "test@example.com", None, "root_test_1", False, "test user when system username set"),
            ("user123", "user123@example.com", None, "service_test_1", False, "user123 when system username set"),
        ],
    )
    def test_user_deletion_with_system_user_flag(self, django_user_model, username, email, password, system_username_setting, is_system_user, test_description):
        """Test user deletion with conditional system user protection based on is_system_user flag"""
        with override_settings(SYSTEM_USERNAME=system_username_setting):
            # Create the user
            if password:
                user = django_user_model.objects.create_user(username=username, email=email, password=password)
            else:
                user = django_user_model.objects.create_user(username=username, email=email)
            user_id = user.id

            # Verify the user exists
            assert django_user_model.objects.filter(id=user_id).exists()

            if is_system_user:
                # System user deletion should raise ValueError
                with pytest.raises(ValueError, match="The system user cannot be deleted"):
                    user.delete()

                # Verify the system user still exists
                assert django_user_model.objects.filter(id=user_id).exists()
            else:
                # Regular user deletion should succeed
                user.delete()

                # Verify the user is deleted
                assert not django_user_model.objects.filter(id=user_id).exists()

    def test_system_user_deletion_with_existing_system_user_fixture(self, system_user):
        """Test system user deletion prevention using the existing system_user fixture"""
        # The system_user fixture provides the actual system user
        system_user_id = system_user.id

        # Verify the system user exists
        assert User.all_objects.filter(id=system_user_id).exists()

        # Attempt to delete the system user - should raise ValueError
        with pytest.raises(ValueError, match="The system user cannot be deleted"):
            system_user.delete()

        # Verify the system user still exists
        assert User.all_objects.filter(id=system_user_id).exists()


@pytest.mark.django_db
class TestUserModel:
    """Additional tests for User model functionality"""

    @pytest.mark.parametrize(
        "username,email,password,expected_username,expected_email",
        [
            ("testuser", "test@example.com", "testpass123", "testuser", "test@example.com"),
            ("user2", "user2@domain.org", "password456", "user2", "user2@domain.org"),
            ("admin_user", "admin@company.com", "securepass", "admin_user", "admin@company.com"),
        ],
    )
    def test_user_creation(self, django_user_model, username, email, password, expected_username, expected_email):
        """Test basic user creation with various inputs"""
        user = django_user_model.objects.create_user(username=username, email=email, password=password)

        assert user.username == expected_username
        assert user.email == expected_email
        assert user.check_password(password)

    @pytest.mark.parametrize(
        "managed_flag,expected_managed",
        [
            (False, False),
            (True, True),
        ],
    )
    def test_managed_user_flag(self, django_user_model, managed_flag, expected_managed):
        """Test that managed flag works correctly"""
        user = django_user_model.objects.create_user(username=f"user_{managed_flag}", managed=managed_flag)
        assert user.managed == expected_managed

    @pytest.mark.parametrize(
        "regular_managed,system_managed,expected_in_default_manager,expected_in_all_manager,test_description",
        [
            (False, True, False, True, "managed user excluded from default manager but in all_objects"),
            (False, False, True, True, "unmanaged user in both managers"),
            (True, True, False, True, "both users managed - both excluded from default but in all_objects"),
        ],
    )
    def test_user_managers(self, django_user_model, regular_managed, system_managed, expected_in_default_manager, expected_in_all_manager, test_description):
        """Test that the user managers work correctly with different managed flag combinations"""
        # Create a regular user
        regular_user = django_user_model.objects.create_user(username="regular", managed=regular_managed)

        # Create a managed user (simulating system user behavior)
        managed_user = django_user_model.objects.create_user(username="managed", managed=system_managed)

        # Get querysets from both managers
        default_users = list(django_user_model.objects.all())
        all_users = list(django_user_model.all_objects.all())

        # Regular users should always be in all_objects
        assert regular_user in all_users

        # Test managed user behavior based on expected parameters
        if expected_in_default_manager:
            assert managed_user in default_users
        else:
            assert managed_user not in default_users

        if expected_in_all_manager:
            assert managed_user in all_users
        else:
            assert managed_user not in all_users

    @pytest.mark.parametrize(
        "use_controller_password,expected_flag",
        [
            (False, False),
            (True, True),
        ],
    )
    def test_use_controller_password_flag(self, django_user_model, use_controller_password, expected_flag):
        """Test that use_controller_password flag works correctly"""
        user = django_user_model.objects.create_user(username=f"controller_user_{use_controller_password}", use_controller_password=use_controller_password)
        assert user.use_controller_password == expected_flag

    @pytest.mark.parametrize(
        "password_input,should_be_usable,test_username",
        [
            ("validpassword", True, "valid_pass_user"),
            (None, False, "none_pass_user"),  # None should become unusable
        ],
    )
    def test_password_handling(self, django_user_model, password_input, should_be_usable, test_username):
        """Test that password handling works correctly for various inputs"""
        if password_input is None:
            user = django_user_model.objects.create_user(username=test_username)
        else:
            user = django_user_model.objects.create_user(username=test_username, password=password_input)

        if should_be_usable:
            assert user.has_usable_password()
            assert user.check_password(password_input)
        else:
            assert not user.has_usable_password()
