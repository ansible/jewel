import copy

from ansible_base.resource_registry.registry import ParentResource, ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor

from aap_gateway_api import models
from aap_gateway_api.utils.models import unique_fields_for_model


class GetOrCreateProcessor(ResourceTypeProcessor):
    def save(self, validated_data, is_new=False):
        # This doesn't _really_ mean "new", it more means that we are POSTing
        if is_new:
            unique_fields = unique_fields_for_model(self.instance.__class__)

            # pop out the unique fields - don't modify the input data, though
            validated_data = copy.deepcopy(validated_data)
            unique_fields = {k: validated_data.pop(k) for k in unique_fields if k in validated_data}

            self.instance, created = self.instance.__class__.objects.update_or_create(**unique_fields, defaults=validated_data)
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
