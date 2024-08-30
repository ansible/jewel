from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from ansible_base.resource_registry.utils.service_backed_sso_pipeline import redirect_to_resource_server
from django.contrib.auth import get_user_model
from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response

User = get_user_model()


@api_view()
def ping(request):
    return Response("pong")


@api_view()
def auth_sso(request):
    backend = request.GET.get("backend")
    username = request.GET.get("username")

    user = User.objects.get(username=username)
    social = user.social_auth.get(provider=backend)

    kwargs = {}

    if backend in ("keycloak", "oidc"):
        kwargs["response"] = {
            "sub": social.extra_data["sub"],
            "preferred_username": social.extra_data["preferred_username"],
        }

    return redirect_to_resource_server(social=social, user=user, **kwargs)


urlpatterns = [
    path("api/v1/", include(resource_api_urls)),
    path("ping/", ping),
    path('login/', include('rest_framework.urls')),
    path('sso/', auth_sso),
]
