import logging

from django.contrib import auth
from django.http import HttpResponseForbidden, JsonResponse
from rest_framework.views import APIView

logger = logging.getLogger("aap.gateway.views")


class LoggedGatewayLoginView(APIView):
    backend = "django.contrib.auth.backends.ModelBackend"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            auth.login(request, request.user, backend=self.backend)
            logger.info(f"User {request.user.username} logged in from Gateway")
            response = JsonResponse({"status": "success"})
            response.status_code = 200
        else:
            logger.warning(f"Login failed for user {request.user.username} from Gateway")
            response = JsonResponse({"status": "failed"})
            response.status_code = 401
        return response


class GatewayVersionView(APIView):
    def get(self, request, *args, **kwargs):
        import pkg_resources

        package = __package__.split('.')[0]
        version = pkg_resources.get_distribution(package).version

        if request.user.is_authenticated:
            logger.info(f"Running gateway client {package} version {version}")
            response = JsonResponse({"package": package, "version": version})
            response.status_code = 200
            return response
        else:
            return HttpResponseForbidden()
