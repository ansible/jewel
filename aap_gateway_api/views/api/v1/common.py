from ansible_base.lib.utils.hashing import hash_serializer_data
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.rbac.api.permissions import AnsibleBaseObjectPermissions
from ansible_base.resource_registry.models import service_id
from django.db import transaction
from django.urls import reverse
from rest_framework import viewsets

from aap_gateway_api.permissions import IsSystemAdminOrAuditor
from aap_gateway_api.utils.resources_client import AllServicesClient, ResourceRequestBody


class GatewayModelViewSet(viewsets.ModelViewSet, AnsibleBaseView):
    permission_classes = [IsSystemAdminOrAuditor]


class RoleModelViewSet(GatewayModelViewSet):
    "Use for models registered in the DAB RBAC permission registry"
    permission_classes = [AnsibleBaseObjectPermissions]

    def filter_queryset(self, qs):
        if hasattr(qs, 'model'):
            cls = qs.model
            qs = cls.access_qs(self.request.user, queryset=qs)

        return super().filter_queryset(qs)


class ResourceAPIUpdateMixin:
    """
    Update the corresponding resource in each service.
    """

    @property
    def _resources_client(self):
        return AllServicesClient()

    @transaction.atomic
    def perform_destroy(self, instance):
        ansible_id = instance.resource.ansible_id
        instance.delete()
        self._resources_client.delete_resource(ansible_id)

    @transaction.atomic
    def perform_update(self, serializer):
        original = serializer.instance
        serializer_class = original.resource.content_type.resource_type.serializer_class
        original_hash = hash_serializer_data(original, serializer_class)

        updated = serializer.save()
        new_hash = hash_serializer_data(updated, serializer_class)

        if original_hash != new_hash:
            self._resources_client.update_resource(
                original.resource.ansible_id, ResourceRequestBody(resource_data=serializer_class(updated).data), partial=False
            )

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        resource = instance.resource
        resource_serializer = resource.content_type.resource_type.serializer_class

        self._resources_client.create_resource(
            ResourceRequestBody(
                ansible_id=instance.resource.ansible_id,
                service_id=str(service_id()),
                resource_type=resource.resource_type,
                resource_data=resource_serializer(instance).data,
            )
        )

    def get_authenticate_header(self, request):
        # HTTP Basic auth is insecure by default, because the basic auth
        # backend does not provide CSRF protection.
        #
        # If you visit `/api/gateway/v1/<something>/` and we return
        # `WWW-Authenticate: Basic ...`, your browser will prompt you for an
        # HTTP basic auth username+password and will store it _in the browser_
        # for subsequent requests.  Because basic auth does not require CSRF
        # validation (because it's commonly used with non-browser clients),
        # browsers that save basic auth in this way are
        # vulnerable to cross-site request forgery:
        #
        # 1. Visit `/api/v2/<something>/` and specify a user+pass for basic auth.
        # 2. Visit a nefarious website and submit a
        #    `<form action='POST' method='https://gateway.example.org/api/gateway/v1/<whatever>/'>`
        # 3. The browser will use your persisted user+pass and your login
        #    session is effectively hijacked.
        #
        # To prevent this, we will _no longer_ send `WWW-Authenticate: Basic ...`
        # headers in responses; this means that unauthenticated /api/gateway/v1/... requests
        # will now return HTTP 401 in-browser, rather than popping up an auth dialog.
        #
        # This means that people who wish to use the interactive API browser
        # must _first_ login in via `/api/login/` to establish a session (which
        # _does_ enforce CSRF).
        #
        # CLI users can _still_ specify basic auth credentials explicitly via
        # a header or in the URL e.g.,
        # `curl https://user:pass@gateway.example.org/api/gateway/v1/something/`
        authorize_url = reverse('authorize')
        return f'Bearer realm=api authorization_url={authorize_url}'
