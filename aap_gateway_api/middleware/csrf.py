from ansible_base.lib.utils.settings import replace_trusted_origins
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.decorators import method_decorator


class GatewayCSRFViewMiddleware(CsrfViewMiddleware):
    """Custom CsrfViewMiddleware for the sole purpose of using custom CSRF_TRUSTED_ORIGINS on the login form

    Every other request ends up getting handled by DRFs SessionAuthentication
    """

    @method_decorator(replace_trusted_origins)
    def _origin_verified(self, request):
        return super()._origin_verified(request)

    @method_decorator(replace_trusted_origins)
    def _check_referer(self, request):
        return super()._check_referer(request)
