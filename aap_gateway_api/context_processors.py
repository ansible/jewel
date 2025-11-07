import uuid

from aap_gateway_api.version import get_api_version


def _check_schema_deprecation(view):
    """Check if view is deprecated using drf-spectacular schema."""
    if not view:
        return False

    try:
        schema = getattr(view, 'schema', None)
        if schema and hasattr(schema, 'is_deprecated'):
            return schema.is_deprecated()
    except (AttributeError, TypeError):
        pass

    return False


def _check_direct_deprecation(view):
    """Check if view has direct deprecated attribute."""
    if not view:
        return False
    return getattr(view, 'deprecated', False)


def _get_deprecated_fields(view):
    """Extract deprecated fields from drf-spectacular serializer annotations."""
    if not view:
        return []

    try:
        serializer_class = view.get_serializer_class()
        if not hasattr(serializer_class, '_spectacular_annotation'):
            return []

        spectacular_annotation = serializer_class._spectacular_annotation
        if not isinstance(spectacular_annotation, dict):
            return []

        return spectacular_annotation.get('deprecate_fields', [])
    except (AttributeError, TypeError):
        return []


def _get_deprecation_message(view, deprecated_fields=None):
    """Generate appropriate deprecation message based on deprecation type."""
    if deprecated_fields:
        field_names = ", ".join(deprecated_fields)
        return getattr(view, 'deprecated_message', f'The following fields on this view have been deprecated: {field_names}')

    return getattr(view, 'deprecated_message', 'This resource has been deprecated and will be removed in a future release.')


def version(request):
    context = getattr(request, 'parser_context', {})
    view = context.get('view')

    # Check deprecation status using helper functions
    deprecated = _check_schema_deprecation(view)

    # Fall back to direct deprecated attribute if schema doesn't provide it
    if not deprecated:
        deprecated = _check_direct_deprecation(view)

    deprecated_message = ''
    if deprecated:
        deprecated_message = _get_deprecation_message(view)
    else:
        # Check for field-level deprecation
        deprecated_fields = _get_deprecated_fields(view)
        if deprecated_fields:
            deprecated = True
            deprecated_message = _get_deprecation_message(view, deprecated_fields)

    return {
        'gateway_version': get_api_version() if get_api_version() != 'development' else uuid.uuid4(),
        'deprecated': deprecated,
        'deprecated_message': deprecated_message,
    }
