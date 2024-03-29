from ansible_base.lib.utils.hashing import hash_serializer_data
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.resource_registry.models import service_id
from django.db import transaction
from rest_framework import viewsets

from aap_gateway_api.utils.resources_client import AllServicesClient, ResourceRequestBody


class GatewayModelViewSet(viewsets.ModelViewSet, AnsibleBaseView):
    pass


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
