"""Demo helper functions with full test coverage for Codecov demonstration."""


def format_user_display_name(user_data):
    """Format a user's display name from user data.

    Args:
        user_data: Dict containing user information with optional
                   'first_name', 'last_name', and 'username' keys.

    Returns:
        Formatted display name string.
    """
    first = user_data.get("first_name", "").strip()
    last = user_data.get("last_name", "").strip()
    username = user_data.get("username", "").strip()

    if first and last:
        return f"{first} {last}"
    elif first:
        return first
    elif last:
        return last
    elif username:
        return username
    else:
        return "Unknown User"


def validate_email(email):
    """Basic email validation for demo purposes.

    Args:
        email: Email string to validate.

    Returns:
        True if email appears valid, False otherwise.
    """
    if not email or not isinstance(email, str):
        return False

    email = email.strip()
    if not email or "@" not in email:
        return False

    parts = email.split("@")
    if len(parts) != 2:
        return False

    local, domain = parts
    if not local or not domain:
        return False

    if "." not in domain:
        return False

    return True
