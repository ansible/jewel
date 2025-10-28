import re
from typing import Optional


def remove_multiple_slashes_from_path(path: Optional[str]) -> Optional[str]:
    """
    Remove multiple consecutive slashes from a URL path, collapsing them into a single slash.

    This function normalizes URL paths by replacing sequences of two or more consecutive
    slashes with a single slash. Single slashes are left unchanged for efficiency.

    Args:
        path: The URL path string to normalize, or None

    Returns:
        The normalized path with consecutive slashes collapsed to single slashes,
        or None if the input is None

    Examples:
        >>> remove_multiple_slashes_from_path('/api//service//path')
        '/api/service/path'
        >>> remove_multiple_slashes_from_path('////')
        '/'
        >>> remove_multiple_slashes_from_path('/api/service/path')
        '/api/service/path'
        >>> remove_multiple_slashes_from_path(None)
        None
    """
    if path is None:
        return None
    return re.sub(r'//+', '/', path)
