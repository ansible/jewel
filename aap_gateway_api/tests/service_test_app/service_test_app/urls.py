from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls
from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view()
def ping(request):
    return Response("pong")


urlpatterns = [
    path("api/v1/", include(resource_api_urls)),
    path("ping/", ping),
]
