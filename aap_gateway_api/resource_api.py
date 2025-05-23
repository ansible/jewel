import copy

from ansible_base.resource_registry.registry import ParentResource, ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor

from aap_gateway_api import models
from aap_gateway_api.utils.models import get_model_lookup_keys


class GetOrCreateProcessor(ResourceTypeProcessor):
    def save(self, validated_data, is_new=False):
        """
        Save the resource instance using the provided validated_data.
        If `is_new` is True (i.e: for POST requests), this method tries to find an existing object using the model's unique fields.
        If found, it updates the existing objects. If not, it creates a new one.
        If `is_new` is False (i.e: for PUT/ PATCH requests), this method sets the fields in validated_data accordingly.
        """

        if is_new:
            # find the fields of this model that can be used to find an existing instance
            lookup_fields = get_model_lookup_keys(self.instance.__class__)

            # get the look up fields kwargs that are present in the validated_data without modifying the input data
            validated_data = copy.deepcopy(validated_data)
            lookup_kwargs = {k: validated_data.pop(k) for k in lookup_fields if k in validated_data}

            # we use update_or_create to ensure idempotency for repeated POSTS
            # this is to support cases where multiple services might make simultaneous requests to create a shared resource.
            # If a resource is being created locally in a service and the resource already exists on Gateway, the local resource
            # should be linked to the resource in Gateway
            self.instance, _ = self.instance.__class__.objects.update_or_create(**lookup_kwargs, defaults=validated_data)
            return self.instance

        for k, val in validated_data.items():
            setattr(self.instance, k, val)

        self.instance.save()
        return self.instance


class APIConfig(ServiceAPIConfig):
    service_type = "aap"
    custom_resource_processors = {
        "shared.organization": GetOrCreateProcessor,
        "shared.team": GetOrCreateProcessor,
        "shared.user": GetOrCreateProcessor,
    }


RESOURCE_LIST = (
    ResourceConfig(
        models.Organization,
        shared_resource=SharedResource(serializer=OrganizationType, is_provider=True),
    ),
    ResourceConfig(models.User, shared_resource=SharedResource(serializer=UserType, is_provider=True), name_field="username"),
    ResourceConfig(
        models.Team,
        shared_resource=SharedResource(serializer=TeamType, is_provider=True),
        parent_resources=[ParentResource(model=models.Organization, field_name="organization")],
    ),
)
