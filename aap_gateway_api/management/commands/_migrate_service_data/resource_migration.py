import logging
from typing import Any, Dict, List, Optional, Tuple

from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE
from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.conf import settings
from django.db import transaction


class ResourceMigrationMixin:
    def _is_service_already_synced(self) -> bool:
        """Check if all resource types for the current service have already been migrated."""
        for resource_type_name in self.resource_types_to_migrate:
            filters = {
                "service_id": self.upstream_service_id,
                "is_partially_migrated": "false",
                "content_type__resource_type__name": resource_type_name,
            }
            data = self.client.list_resources(filters=filters).json()
            if data["count"] > 0:
                return False
        return True

    def update_resource_data(self, resource_type_name: str, original_resource_data: Any) -> Optional[Dict[str, Any]]:
        """
        Attempt to fix invalid resource data to make it valid for migration.

        Currently handles the case where user email addresses are invalid by
        removing them. This allows the migration to continue for users with
        malformed email data.

        Args:
            resource_type_name: Type of resource being processed (e.g., 'shared.user')
            original_resource_data: Serializer instance with validation errors

        Returns:
            Updated resource data dict if fixable, None if not correctable

        Note:
            Only handles email validation errors for user resources currently.
            Can be extended to handle other validation issues as needed.
        """
        # if the resource is a user and there is only one validation error for email field, we can remove the field
        if resource_type_name == SHARED_USER_RESOURCE_TYPE and "email" in original_resource_data.errors and len(original_resource_data.errors.keys()) == 1:
            self._log(
                f"Removing invalid email address '{original_resource_data.data['email']}' for user: {original_resource_data.data['username']}",
                logging.WARNING,
            )
            # we want to update the email to empty string
            updated_resource_data = original_resource_data.data
            updated_resource_data["email"] = ""
            return updated_resource_data

    def _deserialize_and_validate_resource_data(self, upstream_resource: Dict[str, Any], resource_serializer: Any) -> Dict[str, Any]:
        """
        Deserialize and validate resource data using the appropriate serializer.

        This method validates resource data from the upstream service and attempts
        to fix common validation errors. If validation fails and cannot be fixed,
        the migration is halted.

        Args:
            upstream_resource: Complete resource data from upstream service
            resource_serializer: Serializer class for the resource type

        Returns:
            Validated resource data ready for migration

        Raises:
            RuntimeError: If resource validation fails and cannot be corrected
        """
        original_resource_data = resource_serializer(data=upstream_resource["resource_data"])
        resource_type_name = upstream_resource['resource_type']
        resource_ansible_id = upstream_resource['ansible_id']

        if original_resource_data.is_valid(raise_exception=False):
            return original_resource_data.validated_data

        # if the validation failed, attempt to update resource data
        updated_resource_data = self.update_resource_data(resource_type_name, original_resource_data)
        if updated_resource_data is None:
            # updating didn't produce valid data for the resource, hence this resource is invalid
            self._log(
                f"Resource with id '{resource_ansible_id}' of type '{resource_type_name}' failed validation with errors: {str(original_resource_data.errors)}",
                logging.WARNING,
            )
            # Raising exception here to stop migration to draw attention to existence of invalid resources.
            raise RuntimeError("Stopping migration of resources because invalid, non-correctable, resource(s) were encountered.")

        upstream_resource["resource_data"] = updated_resource_data

        return updated_resource_data

    def _initialize_resource_sync_payloads(self, upstream_resource: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Prepare payloads for creating Gateway resources and updating upstream resources."""
        resource_creation_kwargs = {"ansible_id": upstream_resource["ansible_id"]}
        updated_service_resource = {"service_id": str(service_id())}
        return resource_creation_kwargs, updated_service_resource

    def _reconcile_existing_resource(
        self,
        upstream_resource: Dict[str, Any],
        resource_context: Dict[str, Any],
        validated_resource_data: Dict[str, Any],
        updated_service_resource: Dict[str, Any],
    ) -> bool:
        """
        Handle conflicts with existing resources in the gateway.

        This method implements the core logic for handling cases where a resource
        being migrated conflicts with an existing resource in the gateway. It supports
        two (not mutually-exclusive) scenarios:

        1. Same ansible_id: Update existing resource with correct service_id
        2. (Merge) Link upstream resource to existing Gateway resource

        Args:
            upstream_resource: Complete resource data from upstream service
            resource_context: Static data about the resource type
            validated_resource_data: Validated resource data
            updated_service_resource: Data for updating upstream resource

        Returns:
            - create_gateway_resource (bool): True if a new Gateway resource should be created
        """

        resource_type = resource_context["type"]
        unique_fields = resource_context["unique_fields"]
        LocalResourceModel = resource_context["LocalResourceModel"]  # NOSONAR — PascalCase is Django convention for model classes
        create_gateway_resource = True  # default

        # find a dict of key-value pairs for the specified unique fields from validated resource data
        unique_filter_kwargs = {}
        for field_name in unique_fields:
            unique_filter_kwargs[field_name] = validated_resource_data[field_name]

        try:
            existing_resource = LocalResourceModel.objects.select_related("resource").get(**unique_filter_kwargs).resource
        except LocalResourceModel.DoesNotExist:
            return create_gateway_resource

        # if an existing resource is found
        resource_ansible_id = upstream_resource['ansible_id']
        local_data = resource_type.serializer_class(existing_resource.content_object).data
        incoming_data = upstream_resource.get("resource_data", {})

        # case 1: the JWT auth classes create some items with correct ansible_id but without the service_id fully set,
        # so this will correct the service_id and possibly update the stale resource_data
        if str(existing_resource.ansible_id) == resource_ansible_id:
            create_gateway_resource = False
            updated_service_resource["service_id"] = existing_resource.service_id

            if incoming_data == local_data:
                self._log(f"Correcting service_id of {resource_type.name} with name {upstream_resource['name']}.", logging.INFO)
            else:
                updated_service_resource["resource_data"] = local_data
                self._log(f"Updating already-merged {resource_type.name} with name {upstream_resource['name']}.", logging.WARNING)

        # case 2: merge: We only set upstream metadata and ansible_id to be the same as gateway's
        # don't set anything on the gateway
        create_gateway_resource = False
        updated_service_resource.update(
            {
                "ansible_id": existing_resource.ansible_id,
                "resource_data": local_data,
            }
        )
        self._log(f"Merging {resource_type.name} with conflicting name {upstream_resource['name']}.", logging.WARNING)

        return create_gateway_resource

    def _get_filtered_resources(self, filters: Dict[str, Any], resource_type_name: str) -> Tuple[List[Dict[str, Any]], int]:
        """
        Retrieve and filter resources from the upstream service.

        This method fetches resources from the upstream service API and applies
        special filtering logic. For user resources, it excludes the system user
        since Gateway excludes this in its own resources.

        Args:
            filters: API filters to apply when fetching resources
            resource_type_name: Type of resource to fetch

        Returns:
            List of filtered resource data from upstream service

        Note:
            System users are filtered out for 'shared.user' resources to prevent
            conflicts with Gateway's system user handling.
        """
        # Use default page_size here; resource_data triggers per-item content_object
        # serialization that cannot be prefetched, so larger pages risk timeouts.
        filters = {**filters, **self.RESOURCE_DATA_FILTERS}
        data = self.client.list_resources(filters=filters).json()
        self._log(f"Items remaining: {data['count']}", logging.INFO)
        results = data['results']
        # As special case exclude the system user, since Gateway excludes this in its own resources
        if resource_type_name == SHARED_USER_RESOURCE_TYPE:
            # SYSTEM_USERNAME can theoretically vary by service
            # Currently, the system username is None in controller, and in hub and eda it's the same as gateway's,
            # If Hub and EDA system username is updated to != gateway's, we are migrating it too and we should avoid it
            results = [res for res in results if res['name'] != settings.SYSTEM_USERNAME]
        return results, data['count']

    def _process_and_migrate_resource_item(self, upstream_resource_item: Dict[str, Any], resource_context: Dict[str, Any]) -> None:
        """
        Process and migrate a single resource item from upstream to Gateway.

        This method handles the complete migration workflow for a single resource:
        1. Fetch detailed resource data from upstream
        2. Validate and prepare resource data
        3. Handle conflicts with existing resources
        4. Create/update Gateway resource and upstream resource atomically

        Args:
            upstream_resource_item: Basic resource data from upstream service list
            resource_context: Static data about the resource type and migration settings

        Note:
            All operations are wrapped in a database transaction to ensure
            consistency between Gateway and upstream service updates.
        """
        resource_ansible_id = upstream_resource_item["ansible_id"]
        resource_type = resource_context["type"]

        if "resource_data" not in upstream_resource_item:
            raise RuntimeError(
                f"Resource {resource_ansible_id} is missing 'resource_data'. Ensure all services are running a version of DAB that supports extra_fields."
            )

        upstream_resource = upstream_resource_item

        validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

        # Sync superuser flags for user resources
        if resource_context["type_name"] == SHARED_USER_RESOURCE_TYPE:
            upstream_resource = self._sync_user_superuser_flag(upstream_resource, validated_resource_data)
            # Re-validate after potential superuser flag changes
            validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

        resource_creation_kwargs, updated_service_resource = self._initialize_resource_sync_payloads(upstream_resource)

        # handles case with existing resource and figure out if we should create a new resource in gateway or not
        create_gateway_resource = self._reconcile_existing_resource(upstream_resource, resource_context, validated_resource_data, updated_service_resource)

        # Run this as a transaction so that if the REST call to update the resource on the service fails
        # we also rollback any database changes that were made on the gateway.
        with transaction.atomic():
            # determine the resource to use in Gateway
            if create_gateway_resource:
                Resource.create_resource(resource_type, upstream_resource["resource_data"], **resource_creation_kwargs)

            self.client.update_resource(resource_ansible_id, ResourceRequestBody(**updated_service_resource), partial=True)

    def migrate_resource(self, resource_type_name: str) -> None:
        """
        Migrate all resources of a specific type from upstream service to Gateway.

        For each resource, the migration does one of three things:

        - If the resource exists in the gateway (merge): Don't change anything in
          the gateway. Set the ansible_id and service_id on the resource in the service
          to match the gateway's value.
        - If the resource doesn't exist in Gateway: Create a new resource in Gateway
          using the data from the service, including the ansible_id. Set the service_id
          of the resource in the service to match the gateway's ID.
        - If ansible_id matches but service_id differs: Correct the service_id and
          update stale resource_data if needed.

        In all cases, the service_id on the upstream resource is set to the gateway's
        ID, indicating the resource is now managed externally by the gateway.

        This method orchestrates the migration of all resources of a given type by:
        1. Setting up resource type context and configuration
        2. Continuously fetching unmigrated resources from upstream
        3. Processing each resource through the migration pipeline
        4. Stopping when no more resources remain to migrate

        The migration uses a while loop because as resources are migrated,
        their service_id is updated, which removes them from subsequent queries.
        This eliminates the need for complex pagination logic.

        Args:
            resource_type_name: Type of resource to migrate (e.g., 'shared.organization')

        Note:
            Resources are migrated in dependency order: organizations first,
            then teams (which depend on organizations), then users.
        """
        self._log(f"Migrating data for {resource_type_name}", logging.INFO)

        resource_type = self.resource_types_to_migrate[resource_type_name]["type"]

        resource_context = {
            "type": resource_type,
            "type_name": resource_type_name,
            "type_serializer": resource_type.serializer_class,
            "type_name_field": resource_type.get_resource_config().name_field,
            "unique_fields": self.resource_types_to_migrate[resource_type_name]["unique_fields"],
            "LocalResourceModel": resource_type.content_type.model_class(),
        }

        # Each resource that gets updated in the gateway will change the service ID to Gateway's (except for 'shared.user'), and
        # will cause the migrated resources to be filtered out of the server response.
        # 'shared.user' resource type can also be filtered out by setting the 'is_partially_migrated' flag to true
        # Thus, we don't need to deal with pagination here. We just keep calling the list view until the filter returns no items.
        api_call_filters = {
            "service_id": self.upstream_service_id,
            "is_partially_migrated": "false",
            "content_type__resource_type__name": resource_type_name,
        }

        resource_total = None
        resource_processed = 0
        progress_label = f"{self.client.service.api_slug} {resource_type_name} resources"

        # Following 'while True' loop is used because we are modifying the list as we go through it.
        # By changing the service ID or setting partially migrated, we are removing items from the filter,
        # so this doesn't actually use pagination. It just keeps loading the same filter over and over
        # until nothing is left to migrate.
        while True:
            results, count = self._get_filtered_resources(api_call_filters, resource_type_name)
            if resource_total is None:
                resource_total = count + resource_processed

            if len(results) == 0:
                self._log("No more items remaining to migrate.", logging.INFO)
                break

            for upstream_resource_item in results:
                resource_processed += 1
                self._log_progress(progress_label, resource_processed, resource_total)
                self._process_and_migrate_resource_item(upstream_resource_item, resource_context)
