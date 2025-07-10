from typing import Optional
from urllib.parse import urlparse

"""
General utilities that can be called on all requests
"""


def from_proxy(request) -> bool:
    "Return true if request claims to be from a proxy"
    return "HTTP_X_TRUSTED_PROXY" in request.META


def check_csrf_origin(value: str) -> Optional[str]:
    """
    Checks a CSRF Trusted Origin to see if its valid.
    Valid values include:
        * - Any origin
        https://domain.com - A specific server
        https://*.domain.com - A group of subdomains on a domain

    Invalid conditions include:
        - Missing or non http[s] scheme
        - Having a path on the URL
        - Missing a net location (domain)
        - Being unable to parse the value as a URL
    """
    try:
        parts = urlparse(value)

        # We need to support CSRF_TRUSTED_ORIGINS = ["*"] for dev env
        # Handle the special use case of just "*"
        if parts.scheme == '' and parts.netloc == '' and parts.path == '*':
            return None

        # We need to support http or https
        if parts.scheme not in ["https", "http"]:
            return f"The scheme must be https or http only. {value}"

        # and urls without a path
        if parts.path != "":
            return f"The url path needs to be empty. {value}"

        # We need to be able to support wild card patterns https://*.mydomain.com
        if parts.netloc == "":
            return f"The network location should not be empty. {value}"

    except Exception:
        return f"Unable to parse this as an url. {value}"

    return None
