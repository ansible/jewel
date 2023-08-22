import uuid

from aap_gateway_api.utils import get_api_version


def version(request):
    context = getattr(request, 'parser_context', {})
    return {
        'gateway_version': get_api_version() if get_api_version() != 'development' else uuid.uuid4(),
        'deprecated': getattr(context.get('view'), 'deprecated', False),
    }
