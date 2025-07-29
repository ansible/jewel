import copy
from typing import Optional

from ansible_base.rbac.models import DABPermission, RoleDefinition
from ansible_base.resource_registry.registry import ParentResource, ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, RoleDefinitionType, TeamType, UserType
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor
from django.db.models import Model
from rest_framework import serializers
from rest_framework.serializers import ValidationError

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


class GatewayRoleDefinitionProcessor(GetOrCreateProcessor):
    """Gateway is unique because it knows of permissions for all services, and other services do not

    This processes saving of permissions based on the assumption that the client is 1 service.
    A service should have no knowledge of any other non-shared service,
    and if the request claims to, it should be rejected.
    """

    def update_instance_permissions(self, new_perms: list[Model], existing_perms: Optional[list[Model]]):
        # Collect the service slugs that this update will affect permissions for
        new_services = {perm.content_type.service for perm in new_perms}

        if (len(new_services) == 2 and 'shared' in new_services) or len(new_services) == 1:
            # Find existing permissions that impact these services
            if existing_perms is None:
                # For new objects we add all permissions
                self.instance.permissions.add(*new_perms)
            else:
                current_relevant_set = {perm for perm in existing_perms if perm.content_type.service in new_services}
                new_perms_set = set(new_perms)
                to_remove = current_relevant_set - new_perms_set
                to_add = new_perms_set - current_relevant_set

                if to_add:
                    self.instance.permissions.add(*to_add)
                if to_remove:
                    self.instance.permissions.remove(*to_remove)
        else:
            # Unexpected, throw an error
            raise ValidationError('Not expected to set permissions for more than 1 non-shared service')

    def save(self, validated_data, is_new=False):
        new_perms = None  # many-to-many field
        super_validated_data = {}
        for k, val in validated_data.items():
            if k == 'permissions':
                new_perms = val
            else:
                super_validated_data[k] = val

        existing_perms = None
        if new_perms and self.instance.pk:
            existing_perms = list(self.instance.permissions.all())

        super().save(super_validated_data, is_new=is_new)

        # partial updates might not change permissions
        if new_perms:
            self.update_instance_permissions(new_perms=new_perms, existing_perms=existing_perms)

        return self.instance


class StrictPermissionSlugListField(serializers.ListField):
    """Unlike the permissions field in the base serializer in other services, this errors if a permission does not exist"""

    child = serializers.CharField()

    def to_internal_value(self, data):
        slugs = super().to_internal_value(data)
        perms_qs = DABPermission.objects.filter(api_slug__in=slugs)
        perms_by_slug = {p.api_slug: p for p in perms_qs}

        missing = [slug for slug in slugs if slug not in perms_by_slug]
        if missing:
            raise DABPermission.DoesNotExist(f"Permissions not found for api_slug(s): {', '.join(missing)}")

        return [perms_by_slug[slug] for slug in slugs]

    def to_representation(self, value):
        return [perm.api_slug for perm in value.all() if perm is not None]


class GatewayRoleDefinitionType(RoleDefinitionType):
    permissions = StrictPermissionSlugListField()


class APIConfig(ServiceAPIConfig):
    service_type = "aap"
    custom_resource_processors = {
        "shared.organization": GetOrCreateProcessor,
        "shared.team": GetOrCreateProcessor,
        "shared.user": GetOrCreateProcessor,
        "shared.roledefinition": GatewayRoleDefinitionProcessor,
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
    ResourceConfig(
        RoleDefinition,
        shared_resource=SharedResource(serializer=GatewayRoleDefinitionType, is_provider=True),
    ),
)
