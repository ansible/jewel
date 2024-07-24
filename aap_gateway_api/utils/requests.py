"""
    General utilities that can be called on all requests
"""


def from_proxy(request) -> bool:
    "Return true if request claims to be from a proxy"
    return "HTTP_X_TRUSTED_PROXY" in request.META
