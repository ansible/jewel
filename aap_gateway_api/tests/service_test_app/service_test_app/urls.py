from ansible_base.rbac.api.router import router as rbac_router
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from ansible_base.resource_registry.utils.service_backed_sso_pipeline import redirect_to_resource_server
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
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

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        user = User.objects.get(username=settings.RENAMED_USERNAME_PREFIX + username)

    try:
        social = user.social_auth.get(provider=backend)
    except ObjectDoesNotExist:
        raise Exception(f'Could not find {backend} social auth for {user.username}, exiting:\n{user.social_auth.all()}')

    kwargs = {}

    if backend in ("keycloak", "oidc"):
        kwargs["response"] = {
            "sub": social.extra_data["sub"],
            "preferred_username": social.extra_data["preferred_username"],
        }

    return redirect_to_resource_server(social=social, user=user, **kwargs)


urlpatterns = [
    path("api/v1/", include(resource_api_urls)),
    path("api/v1/", include(rbac_router.urls)),
    path("ping/", ping),
    path('login/', include('rest_framework.urls')),
    path('sso/', auth_sso),
]
