"""
Test the preference management fixtures to ensure they provide proper isolation.
"""

from aap_gateway_api.utils.preferences import get_preference_value


class TestPreferenceFixtures:
    def test_preference_manager_single_set(self, preference_manager):
        """Test that preference_manager.set properly isolates a single preference."""
        # Check original value
        original_value = get_preference_value("local_login", "password_min_upper")
        assert original_value == 0  # Default value

        with preference_manager.set("local_login", "password_min_upper", 2):
            # Inside context, value should be changed
            assert get_preference_value("local_login", "password_min_upper") == 2

        # After context, value should be restored
        assert get_preference_value("local_login", "password_min_upper") == original_value

    def test_preference_manager_single(self, preference_manager):
        """Test that preference_manager.set properly isolates a single preference."""
        original_value = get_preference_value("local_login", "password_min_special")
        assert original_value == 0  # Default value

        with preference_manager.set("local_login", "password_min_special", 3):
            assert get_preference_value("local_login", "password_min_special") == 3

        assert get_preference_value("local_login", "password_min_special") == original_value

    def test_preference_manager_multiple(self, preference_manager):
        """Test that preference_manager.set_multiple properly isolates multiple preferences."""
        # Get original values
        original_upper = get_preference_value("local_login", "password_min_upper")
        original_special = get_preference_value("local_login", "password_min_special")
        original_length = get_preference_value("local_login", "password_min_length")

        assert original_upper == 0
        assert original_special == 0
        assert original_length == 0

        with preference_manager.set_multiple(
            {
                ("local_login", "password_min_upper"): 2,
                ("local_login", "password_min_special"): 2,
                ("local_login", "password_min_length"): 8,
            }
        ):
            # Inside context, all values should be changed
            assert get_preference_value("local_login", "password_min_upper") == 2
            assert get_preference_value("local_login", "password_min_special") == 2
            assert get_preference_value("local_login", "password_min_length") == 8

        # After context, all values should be restored
        assert get_preference_value("local_login", "password_min_upper") == original_upper
        assert get_preference_value("local_login", "password_min_special") == original_special
        assert get_preference_value("local_login", "password_min_length") == original_length

    def test_preference_isolation_between_tests(self):
        """Test that preferences don't leak between tests (this test should see default values)."""
        # This test should see the default values, even if previous tests changed them
        assert get_preference_value("local_login", "password_min_upper") == 0
        assert get_preference_value("local_login", "password_min_special") == 0
        assert get_preference_value("local_login", "password_min_length") == 0

    def test_exception_handling(self, preference_manager):
        """Test that preferences are restored even if an exception occurs."""
        original_value = get_preference_value("local_login", "password_min_upper")

        try:
            with preference_manager.set("local_login", "password_min_upper", 5):
                assert get_preference_value("local_login", "password_min_upper") == 5
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected exception

        # Value should be restored despite the exception
        assert get_preference_value("local_login", "password_min_upper") == original_value
