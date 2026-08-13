import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE
from ansible_base.resource_registry.models import Resource, service_id
from django.conf import settings
from django.db import transaction


class ResourceMigrationMixin:
    def _is_service_already_synced(self) -> bool:
        """Check if all migratable resource types for the current service have already been migrated."""
        response = self.client.list_resources(
            filters={
                "service_id": self.upstream_service_id,
                "is_partially_migrated": "false",
                "content_type__resource_type__name__in": ",".join(self.resource_types_to_migrate),
            }
        ).json()

        if response["count"] > 0:
            results = response.get("results", [])
            if settings.SYSTEM_USERNAME:
                results = [r for r in results if r.get("resource_type") != SHARED_USER_RESOURCE_TYPE or r.get("name") != settings.SYSTEM_USERNAME]
            if results or response["count"] > len(response.get("results", [])):
                return False

        has_resources = self.client.list_resources(filters={"service_id": self.upstream_service_id}).json()
        if has_resources["count"] == 0:
            self._log(
                "Upstream resource registry is empty — will attempt migration (registry may not be populated yet).",
                logging.WARNING,
            )
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
        updated_service_resource = {"new_service_id": str(service_id())}
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
            updated_service_resource["new_service_id"] = str(existing_resource.service_id)

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

    @staticmethod
    def _build_bulk_update_item(resource_ansible_id: str, updated_service_resource: Dict[str, Any]) -> Dict[str, Any]:
        """Build a single bulk-update payload item from the reconciled service resource fields."""
        bulk_item: Dict[str, Any] = {"ansible_id": resource_ansible_id}
        if "new_service_id" in updated_service_resource:
            bulk_item["new_service_id"] = updated_service_resource["new_service_id"]
        if "is_partially_migrated" in updated_service_resource:
            bulk_item["is_partially_migrated"] = updated_service_resource["is_partially_migrated"]
        if "ansible_id" in updated_service_resource:
            bulk_item["new_ansible_id"] = str(updated_service_resource["ansible_id"])
        if "resource_data" in updated_service_resource:
            bulk_item["resource_data"] = updated_service_resource["resource_data"]
        return bulk_item

    MAX_BULK_CHUNK_SIZE = 1000
    MAX_TRANSIENT_RETRIES = 3
    TRANSIENT_STATUS_CODES = {502, 503, 504}

    _RETRY_SENTINEL = object()
    _PERMANENT_FAILURE = object()

    def _send_bulk_update(self, bulk_update_items: List[Dict[str, Any]]) -> int:
        """Send bulk update to upstream and return the number of successfully updated items.

        Items are chunked to respect the upstream MAX_BULK_SIZE limit (1000).
        Transient HTTP errors (502/503/504, network errors) are retried with
        exponential backoff. Permanent errors (4xx) fail immediately.
        Per-item errors from successful responses are logged as warnings.

        If a chunk fails permanently, raises RuntimeError immediately since the
        failure is systemic (e.g., endpoint doesn't exist) and will never recover.
        """
        total_updated = 0
        for i in range(0, len(bulk_update_items), self.MAX_BULK_CHUNK_SIZE):
            chunk = bulk_update_items[i : i + self.MAX_BULK_CHUNK_SIZE]
            result = self._send_bulk_update_chunk(chunk)
            if result is self._PERMANENT_FAILURE:
                raise RuntimeError(
                    f"Bulk update permanent failure at chunk index {i}. The upstream endpoint is unavailable or rejecting requests — migration cannot proceed."
                )
            total_updated += result
        return total_updated

    @staticmethod
    def _extract_error_detail(resp) -> str:
        """Extract actionable error detail from a response.

        Tries to parse JSON (which usually contains a 'detail' field) for
        concise error info. Falls back to truncated response text for HTML
        proxy error pages.
        """
        try:
            data = resp.json()
            if isinstance(data, dict) and "detail" in data:
                return str(data["detail"])[:500]
            return str(data)[:500]
        except (ValueError, AttributeError):
            return resp.text[:500] if hasattr(resp, "text") else "(no response body)"

    def _should_retry(self, attempt: int, reason: str, detail: str) -> bool:
        """Decide whether to retry a transient error, logging appropriately.

        Returns True if the caller should retry (sleep already performed),
        False if retries are exhausted (error already logged).
        """
        if attempt < self.MAX_TRANSIENT_RETRIES - 1:
            wait = 2**attempt
            self._log(
                f"Bulk update {reason} (attempt {attempt + 1}/{self.MAX_TRANSIENT_RETRIES}): {detail}. Retrying in {wait}s.",
                logging.WARNING,
            )
            time.sleep(wait)
            return True
        self._log(
            f"Bulk update failed after {self.MAX_TRANSIENT_RETRIES} attempts — {reason}: {detail}",
            logging.ERROR,
        )
        return False

    def _handle_http_error(self, exc: requests.exceptions.HTTPError, attempt: int) -> object:
        """Classify an HTTPError as transient or permanent and act accordingly.

        Called when raise_if_bad_request=True causes the client to raise
        HTTPError for non-2xx responses. Returns _RETRY_SENTINEL for transient
        5xx errors (if retries remain), or _PERMANENT_FAILURE for permanent errors.
        """
        if exc.response is None:
            self._log(
                f"HTTPError raised without a response object: {str(exc)[:500]}",
                logging.ERROR,
            )
            return self._PERMANENT_FAILURE
        status = exc.response.status_code
        body = self._extract_error_detail(exc.response)
        if status in self.TRANSIENT_STATUS_CODES:
            if self._should_retry(attempt, f"HTTP {status}", body):
                return self._RETRY_SENTINEL
            return self._PERMANENT_FAILURE
        self._log(
            f"Bulk update returned HTTP {status} (permanent error, will not retry): {body}",
            logging.ERROR,
        )
        return self._PERMANENT_FAILURE

    def _try_bulk_update_once(self, chunk: List[Dict[str, Any]], attempt: int) -> object:
        """Execute one bulk-update attempt.

        Returns the parsed response dict on success, _RETRY_SENTINEL if a
        transient error occurred and retries remain, or _PERMANENT_FAILURE if
        the request failed permanently.

        Note: The client is created with raise_if_bad_request=True, so non-2xx
        responses raise HTTPError (a subclass of RequestException) before
        returning. We catch HTTPError first to distinguish transient (5xx) from
        permanent (4xx) errors, then catch the broader RequestException for
        genuine network/connection failures.
        """
        try:
            resp = self.client.bulk_update_resources(chunk)
        except requests.exceptions.HTTPError as exc:
            return self._handle_http_error(exc, attempt)
        except requests.exceptions.RequestException as exc:
            if self._should_retry(attempt, "network error", str(exc)):
                return self._RETRY_SENTINEL
            return self._PERMANENT_FAILURE

        if resp.status_code in self.TRANSIENT_STATUS_CODES:
            if self._should_retry(attempt, f"HTTP {resp.status_code}", self._extract_error_detail(resp)):
                return self._RETRY_SENTINEL
            return self._PERMANENT_FAILURE

        if resp.status_code != 200:
            self._log(
                f"Bulk update returned HTTP {resp.status_code} (permanent error, will not retry): {self._extract_error_detail(resp)}",
                logging.ERROR,
            )
            return self._PERMANENT_FAILURE

        try:
            return resp.json()
        except ValueError:
            if self._should_retry(attempt, "non-JSON response", resp.text[:500]):
                return self._RETRY_SENTINEL
            return self._PERMANENT_FAILURE

    def _send_bulk_update_chunk(self, chunk: List[Dict[str, Any]]):
        """Send a single chunk of bulk update items with retry logic for transient errors.

        Returns the number of successfully updated items, or _PERMANENT_FAILURE
        if the request failed permanently.
        """
        for attempt in range(self.MAX_TRANSIENT_RETRIES):
            result = self._try_bulk_update_once(chunk, attempt)
            if result is self._RETRY_SENTINEL:
                continue
            if result is self._PERMANENT_FAILURE:
                return self._PERMANENT_FAILURE
            return self._process_bulk_response(result)
        return self._PERMANENT_FAILURE

    def _process_bulk_response(self, resp_data) -> int:
        """Extract the updated count from a successful bulk-update response, logging per-item errors."""
        if not isinstance(resp_data, dict):
            self._log(
                f"Bulk update returned unexpected response type ({type(resp_data).__name__}): {str(resp_data)[:500]}",
                logging.ERROR,
            )
            return 0
        for err in resp_data.get("errors") or []:
            self._log(
                f"Bulk-update per-item failure for {err.get('ansible_id')}: {err.get('error')}",
                logging.WARNING,
            )
        return resp_data.get("updated", 0)

    def _process_resource_page_batch(self, results: List[Dict[str, Any]], resource_context: Dict[str, Any]) -> int:
        """
        Process and migrate a batch of resource items from a single API page.

        Follows the same pattern as role assignments: validates all items,
        performs bulk local writes, then sends a single bulk HTTP call to
        update upstream. Per-item failures are logged as warnings rather than
        aborting the entire page — failed items will reappear on the next
        iteration since their service_id/is_partially_migrated was not updated.

        Args:
            results: List of resource items from the upstream service API page
            resource_context: Static data about the resource type

        Returns:
            Number of items successfully processed in this batch
        """
        resource_type = resource_context["type"]
        bulk_update_items = []
        create_operations = []

        # NOTE: If any item fails validation, the entire page is aborted via exception.
        # Validation failures indicate systemic issues (incompatible DAB version, corrupt
        # data) rather than per-item corruption, so halting is the correct behavior.
        for upstream_resource_item in results:
            resource_ansible_id = upstream_resource_item["ansible_id"]

            if "resource_data" not in upstream_resource_item:
                raise RuntimeError(
                    f"Resource {resource_ansible_id} is missing 'resource_data'. Ensure all services are running a version of DAB that supports extra_fields."
                )

            upstream_resource = upstream_resource_item
            validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

            if resource_context["type_name"] == SHARED_USER_RESOURCE_TYPE:
                upstream_resource = self._sync_user_superuser_flag(upstream_resource, validated_resource_data)
                validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

            resource_creation_kwargs, updated_service_resource = self._initialize_resource_sync_payloads(upstream_resource)
            create_gateway_resource = self._reconcile_existing_resource(upstream_resource, resource_context, validated_resource_data, updated_service_resource)

            if create_gateway_resource:
                create_operations.append((resource_type, upstream_resource["resource_data"], resource_creation_kwargs))

            bulk_update_items.append(self._build_bulk_update_item(resource_ansible_id, updated_service_resource))

        # Create gateway resources locally. If a resource already exists (e.g. from a
        # previous interrupted run), the reconcile logic above will have set
        # create_gateway_resource=False, so duplicates are safe.
        # NOTE: Local creates are committed BEFORE the bulk update is sent.
        # If the bulk update fails, local resources persist but upstream is not
        # updated. This is safe because _reconcile_existing_resource detects
        # existing resources on retry, and the upstream filter naturally retries
        # unmigrated items.
        with transaction.atomic():
            for rt, resource_data, creation_kwargs in create_operations:
                Resource.create_resource(rt, resource_data, **creation_kwargs)

        # Send bulk update to upstream service.
        if bulk_update_items:
            return self._send_bulk_update(bulk_update_items)

        # No items to update upstream (results was empty or all filtered out).
        return 0

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
        consecutive_zero_progress = 0
        max_zero_progress_pages = 3
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

            batch_size = self._process_resource_page_batch(results, resource_context)
            if batch_size == 0:
                consecutive_zero_progress += 1
                if consecutive_zero_progress >= max_zero_progress_pages:
                    raise RuntimeError(
                        f"Migration stalled: {max_zero_progress_pages} consecutive pages made no forward progress. Check upstream service availability."
                    )
            else:
                consecutive_zero_progress = 0

            resource_processed += batch_size
            if batch_size < len(results):
                self._log(
                    f"Only {batch_size}/{len(results)} items updated upstream. Failed items remain unmigrated and will reappear on the next page fetch.",
                    logging.WARNING,
                )
            self._log_progress(progress_label, resource_processed, resource_total)
