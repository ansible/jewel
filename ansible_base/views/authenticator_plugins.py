from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.authentication.authenticators import get_authenticator_class, get_authenticator_plugins


class AuthenticatorPluginView(APIView):
    def get(self, request, format=None):
        plugins = get_authenticator_plugins()
        resp = []

        for p in plugins:
            klass = get_authenticator_class(p)
            config = klass.configuration_class()
            config_schema = config.get_configuration_schema()
            resp.append({"type": p, "configuration_schema": config_schema, "documentation_url": getattr(config, "documentation_url", None)})

        return Response(resp)
