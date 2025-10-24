from typing import Optional


def normalize_comma_separated_list(value: Optional[str]) -> str:
    """
    Normalize a comma-separated list by removing empty values and extra whitespace.

    This function takes a string containing comma-separated values, trims whitespace
    from each value, removes empty values, and returns a normalized comma-separated string.

    Args:
        value: A comma-separated string to normalize, or None

    Returns:
        A normalized comma-separated string with unique values (order preserved),
        or empty string if the input is None or results in no valid values.
        Returns empty string (not None) to align with Django CharField behavior
        where blank=True, null=False.

    Examples:
        >>> normalize_comma_separated_list('tag1, tag2, tag3')
        'tag1,tag2,tag3'
        >>> normalize_comma_separated_list('tag1, , tag2,  , tag3')
        'tag1,tag2,tag3'
        >>> normalize_comma_separated_list('  tag1  ,  tag2  ')
        'tag1,tag2'
        >>> normalize_comma_separated_list('')
        ''
        >>> normalize_comma_separated_list(None)
        ''
    """
    if not value:
        return ""

    # Use dict.fromkeys() to preserve order while removing duplicates (Python 3.7+)
    cleaned_values = []
    for item in value.split(','):
        item = item.strip()
        if item:
            cleaned_values.append(item)

    # Remove duplicates while preserving order
    unique_values = list(dict.fromkeys(cleaned_values))

    result = ','.join(unique_values)
    return result if result else ""
