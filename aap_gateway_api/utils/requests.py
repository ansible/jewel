import ipaddress
from typing import Optional
from urllib.parse import urlparse

from ansible_base.lib.utils.validation import validate_domain_name

"""
General utilities that can be called on all requests
"""


def from_proxy(request) -> bool:
    "Return true if request claims to be from a proxy"
    return "HTTP_X_TRUSTED_PROXY" in request.META


def _validate_url_structure(parts, value: str) -> Optional[str]:
    """Validate basic URL structure for CSRF origins."""
    # Django 4.0+ requires scheme to be present
    if parts.scheme not in ["https", "http"]:
        return f"The origin must start with either http:// or https://. Got: {value}"

    # Network location (domain) must be present
    if not parts.netloc:
        return f"The hostname should not be empty. Got: {value}"

    # URLs must not have a path, query, or fragment
    if parts.path not in ("", "/"):
        return f"The origin must include only the scheme and hostname (no path). Got: {value}"

    if parts.query:
        return f"The origin must not include query parameters. Got: {value}"

    if parts.fragment:
        return f"The origin must not include fragments. Got: {value}"

    return None


def _validate_wildcard_domain(netloc: str, value: str) -> Optional[str]:
    """Validate wildcard domain patterns for CSRF origins."""
    # Wildcard must be at the start and followed by a dot
    if not netloc.startswith("*."):
        return f"wildcard must be at the start of the domain and followed by a dot (e.g., '*.example.com'). Got: {value}"

    # Check that there's a valid domain after the wildcard
    domain_part = netloc[2:]  # Remove "*."
    if not domain_part:
        return f"wildcard domain must have a valid domain after '*.'. Got: {value}"

    # Ensure no additional wildcards
    if "*" in domain_part:
        return f"only one wildcard at the beginning is allowed. Got: {value}"

    # Wildcards should not be used with IP addresses
    try:
        ipaddress.ip_address(domain_part)
        return f"wildcards cannot be used with IP addresses. Got: {value}"
    except ValueError:
        # Not an IP address, validate as domain name
        # For wildcard domains, we need at least a valid TLD structure
        # Special case: localhost is allowed even without dots
        if "." not in domain_part and domain_part.lower() != 'localhost':
            return f"wildcard domain must have a valid domain after '*.'. Got: {value}"

        # Special case: localhost is always valid for wildcards
        if domain_part.lower() != 'localhost' and not validate_domain_name(domain_part):
            return f"invalid domain name after wildcard: '{domain_part}'. Got: {value}"

    return None


def _validate_regular_hostname(hostname: str, value: str) -> Optional[str]:
    """Validate regular (non-wildcard) hostnames for CSRF origins."""
    if not hostname:
        return None

    # Check if it's an IP address (IPv4 or IPv6)
    try:
        ipaddress.ip_address(hostname)
        # It's an IP address, which is valid
        return None
    except ValueError:
        # Not an IP address, validate as domain name
        # Handle special case of localhost
        if hostname.lower() != 'localhost' and not validate_domain_name(hostname):
            return f"invalid domain name: '{hostname}'. Got: {value}"

    return None


def check_csrf_origin(value: str) -> Optional[str]:
    """
    Checks a CSRF Trusted Origin to see if its valid according to Django 4.2+ requirements.

    Valid values include:
        * - Any origin (for development only)
        https://domain.com - A specific server
        https://*.domain.com - A group of subdomains on a domain
        http://localhost:8000 - localhost with port number
        https://127.0.0.1 - IPv4 address
        https://192.168.1.1:8080 - IPv4 address with port
        https://[::1] - IPv6 address
        https://[2001:db8::1]:8080 - IPv6 address with port

    Invalid conditions include:
        - Missing or non http[s] scheme (required since Django 4.0+)
        - Having a path, query, or fragment on the URL
        - Missing a net location (domain)
        - Invalid wildcard placement (must be at start of netloc)
        - Wildcards used with IP addresses
        - Being unable to parse the value as a URL
    """
    # Handle non-string types first
    if not isinstance(value, str):
        return f"Unable to parse this as a URL. Got: {value}. Error: Expected string type"

    # Handle the special case of "*" for development environments
    if value == "*":
        return None

    try:
        parts = urlparse(value)

        # Validate basic URL structure
        structure_error = _validate_url_structure(parts, value)
        if structure_error:
            return structure_error

        # Validate hostname based on whether it contains wildcards
        if "*" in parts.netloc:
            return _validate_wildcard_domain(parts.netloc, value)
        else:
            return _validate_regular_hostname(parts.hostname, value)

    except Exception as e:
        return f"Unable to parse this as a URL. Got: {value}. Error: {str(e)}"
