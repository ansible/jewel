"""Tests for demo_helper utility functions with 100% coverage."""

import pytest

from aap_gateway_api.utils.demo_helper import format_user_display_name, validate_email


class TestFormatUserDisplayName:
    """Test format_user_display_name function."""

    def test_full_name(self):
        """Test formatting with both first and last name."""
        user_data = {"first_name": "John", "last_name": "Doe"}
        assert format_user_display_name(user_data) == "John Doe"

    def test_first_name_only(self):
        """Test formatting with only first name."""
        user_data = {"first_name": "John"}
        assert format_user_display_name(user_data) == "John"

    def test_last_name_only(self):
        """Test formatting with only last name."""
        user_data = {"last_name": "Doe"}
        assert format_user_display_name(user_data) == "Doe"

    def test_username_only(self):
        """Test formatting with only username."""
        user_data = {"username": "jdoe"}
        assert format_user_display_name(user_data) == "jdoe"

    def test_empty_data(self):
        """Test formatting with empty user data."""
        user_data = {}
        assert format_user_display_name(user_data) == "Unknown User"

    def test_whitespace_handling(self):
        """Test that whitespace is properly stripped."""
        user_data = {"first_name": "  John  ", "last_name": "  Doe  "}
        assert format_user_display_name(user_data) == "John Doe"

    def test_empty_strings(self):
        """Test formatting with empty string values."""
        user_data = {"first_name": "", "last_name": "", "username": ""}
        assert format_user_display_name(user_data) == "Unknown User"


class TestValidateEmail:
    """Test validate_email function."""

    def test_valid_email(self):
        """Test validation of valid email addresses."""
        assert validate_email("user@example.com") is True
        assert validate_email("john.doe@company.co.uk") is True

    def test_invalid_no_at_sign(self):
        """Test validation fails without @ sign."""
        assert validate_email("userexample.com") is False

    def test_invalid_multiple_at_signs(self):
        """Test validation fails with multiple @ signs."""
        assert validate_email("user@@example.com") is False
        assert validate_email("user@domain@example.com") is False

    def test_invalid_no_domain(self):
        """Test validation fails without domain part."""
        assert validate_email("user@") is False

    def test_invalid_no_local(self):
        """Test validation fails without local part."""
        assert validate_email("@example.com") is False

    def test_invalid_no_dot_in_domain(self):
        """Test validation fails without dot in domain."""
        assert validate_email("user@example") is False

    def test_invalid_empty_string(self):
        """Test validation fails for empty string."""
        assert validate_email("") is False

    def test_invalid_none(self):
        """Test validation fails for None."""
        assert validate_email(None) is False

    def test_invalid_non_string(self):
        """Test validation fails for non-string input."""
        assert validate_email(123) is False
        assert validate_email([]) is False

    def test_whitespace_handling(self):
        """Test that whitespace is properly handled."""
        assert validate_email("  user@example.com  ") is True
