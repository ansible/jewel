import uuid

from aap_gateway_api.version import get_api_version


def version(request):
    context = getattr(request, 'parser_context', {})
    return {
        'gateway_version': get_api_version() if get_api_version() != 'development' else uuid.uuid4(),
        'deprecated': getattr(context.get('view'), 'deprecated', False),
        'deprecated_message': getattr(context.get('view'), 'deprecated_message', 'This resource has been deprecated and will be removed in a future release.'),
    }
