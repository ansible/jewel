import logging
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction

from aap_gateway_api.models import DefaultServiceType, MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, ServiceType
from aap_gateway_api.utils.resources_client import GWResourceAPIClient

logger = logging.getLogger('aap_gateway_api.management.commands.migrate_service_data')
User = get_user_model()


class Command(BaseCommand):
    """
    Django management command for migrating organizations, teams, and users from existing AAP
    installations into the Gateway.

    This command facilitates the migration of resources from upstream AAP services (Controller,
    Hub, EDA) into the Gateway's resource registry system. It handles:

    - Organizations: Can be merged or kept separate based on configuration
    - Teams: Can be merged or kept separate based on configuration
    - Users: Always merged for the admin user, others are partially migrated

    The migration process involves:
    1. Connecting to the upstream service via API
    2. Fetching resource data from the upstream service
    3. Creating or updating resources in the Gateway
    4. Updating upstream resources with Gateway service IDs

    Important: Users are never fully migrated - only the admin user is merged,
    while other users are partially migrated to preserve authentication state.
    """

    help = """Migrate Organizations and teams from existing AAP installations into the Gateway.

    There is no option to control merging of users, because users are never migrated.
    The exception is that the provided --username, which will be merged."""

    def add_arguments(self, parser) -> None:
        """
        Add command line arguments for the migrate_service_data command.

        Args:
            parser: ArgumentParser instance for adding command arguments
        """
        services = ServiceAPIRoute.objects.exclude(service_cluster__service_type__name=DefaultServiceType.GATEWAY.value).values_list("api_slug", flat=True)

        parser.add_argument(
            "--api-slug",
            type=str,
            help="[IGNORED] API slug for the ServiceAPIRoute that you wish to migrate. This flag is now ignored as the command processes all services.",
            choices=services,
            required=False,
        )
        parser.add_argument("--username", type=str, help="Username for the AAP Gateway user to use on the request. Must be an admin user.", required=True)
        parser.add_argument(
            "--merge-teams",
            type=bool,
            help=("[IGNORED] If true, teams with the same names on different services will be combined. " "This flag is now ignored and defaults to True."),
            default=True,
        )
        parser.add_argument(
            "--merge-organizations",
            type=bool,
            help=(
                "[IGNORED] If true, organizations with the same names on different services will be combined. " "This flag is now ignored and defaults to True."
            ),
            default=True,
        )

    def handle(self, *args, **options) -> None:
        """
        Main entry point for the migrate_service_data command.

        Orchestrates the migration process by:
        1. Validating inputs and setting up configuration
        2. Establishing connection to upstream service
        3. Migrating controller admin user if needed
        4. Migrating resources in dependency order (orgs -> teams -> users)

        Args:
            *args: Positional arguments (unused)
            **options: Command options containing api_slug, username, merge settings

        Raises:
            CommandError: If service doesn't exist, user doesn't exist, or migration fails
        """
        # Show warnings for ignored flags
        if options.get("api_slug"):
            self.stderr.write(
                self.style.WARNING("Warning: --api-slug flag is ignored. The command now processes all services with DefaultServiceType (excluding gateway).")
            )

        if "merge_teams" in options:
            self.stderr.write(self.style.WARNING("Warning: --merge-teams flag is ignored. The default value is now True."))

        if "merge_organizations" in options:
            self.stderr.write(self.style.WARNING("Warning: --merge-organizations flag is ignored. The default value is now True."))

        # Force merge options to True as per requirements
        merge_teams = True
        merge_organizations = True
        username = options["username"]

        # The order here matters. Organizations need to be migrated first.
        self.resource_types_to_migrate = OrderedDict()

        self.resource_types_to_migrate["shared.organization"] = {
            "merge": merge_organizations,
            "type": ResourceType.objects.get(name="shared.organization"),
            "unique_fields": [
                "name",
            ],
        }
        self.resource_types_to_migrate["shared.team"] = {
            "merge": merge_teams,
            "type": ResourceType.objects.get(name="shared.team"),
            "unique_fields": [
                "name",
                "organization",
            ],
        }
        self.resource_types_to_migrate["shared.user"] = {
            "merge": True,  # only indicates we merge the admin user
            "type": ResourceType.objects.get(name="shared.user"),
            "unique_fields": [
                "username",
            ],
        }

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Username {username} does not exist")

        # Get all services with DefaultServiceType in exact order: controller, hub, eda
        service_type_order = [
            DefaultServiceType.CONTROLLER.value,
            DefaultServiceType.HUB.value,
            DefaultServiceType.EDA.value,
        ]

        service_apis_dict = {
            api.service_cluster.service_type.name: api for api in ServiceAPIRoute.objects.filter(service_cluster__service_type__name__in=service_type_order)
        }

        service_apis = [service_apis_dict[service_type] for service_type in service_type_order if service_type in service_apis_dict]

        if not service_apis:
            raise CommandError(f"No services found with expected service types: {', '.join(service_type_order)}")

        self.stdout.write(f"Found {len(service_apis)} services to migrate: {', '.join(api.api_slug for api in service_apis)}")

        # Track migration results
        migration_results = {}
        successful_services = []
        failed_services = []

        # Process each service
        for service_api in service_apis:
            service_slug = service_api.api_slug
            self.stdout.write(f"\n=== Processing service: {service_slug} ===")

            try:
                # Process a single service migration
                success, error_msg = self._migrate_single_service(service_api, service_slug, user)
                if success:
                    successful_services.append(service_slug)
                    migration_results[service_slug] = {"status": "success", "error": None}
                else:
                    failed_services.append(service_slug)
                    migration_results[service_slug] = {"status": "failed", "error": error_msg}
            except Exception as e:
                error_msg = str(e)
                self.stderr.write(f"Error migrating service {service_slug}: {error_msg}")
                failed_services.append(service_slug)
                migration_results[service_slug] = {"status": "failed", "error": error_msg}
                continue

        # Provide comprehensive summary
        self.stdout.write("\n=== Migration Summary ===")
        self.stdout.write(f"Total services processed: {len(migration_results)}")
        self.stdout.write(f"Successful migrations: {len(successful_services)}")
        self.stdout.write(f"Failed migrations: {len(failed_services)}")

        if successful_services:
            self.stdout.write(f"\nSuccessfully migrated services: {', '.join(successful_services)}")

        if failed_services:
            self.stderr.write("\nFailed to migrate the following services:")
            for service_slug in failed_services:
                error = migration_results[service_slug]["error"]
                self.stderr.write(f"  - {service_slug}: {error}")

            raise CommandError(f"Migration failed for {len(failed_services)} service(s): {', '.join(failed_services)}. " "See error details above.")
        else:
            # Validate superuser consistency across all services
            self._ensure_superuser_consistency(service_apis, user)
            self.stdout.write("\nAll services migration completed successfully!")

    def _migrate_single_service(
        self,
        service_api: ServiceAPIRoute,
        service_slug: str,
        user: AbstractUser,
    ) -> Tuple[bool, Optional[str]]:
        """
        Migrate data from a single service.

        Args:
            service_api: ServiceAPIRoute instance for the service
            service_slug: API slug for the service
            user: User to perform the migration as

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # TODO: switch user out for _system. Need to get more fine grained permissions in resources
        # api merged first.
        self.client = GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        self.stdout.write("Starting migration")

        self.stdout.write("Getting service metadata")
        service_metadata = self.client.get_service_metadata().json()

        self.upstream_service_id = service_metadata["service_id"]
        # Preserve coercion of awx -> controller and galaxy -> hub
        if service_metadata["service_type"].casefold() == "awx".casefold():
            service_type_name = DefaultServiceType.CONTROLLER.value
        elif service_metadata["service_type"].casefold() == "galaxy".casefold():
            service_type_name = DefaultServiceType.HUB.value
        else:
            service_type_name = service_metadata["service_type"]
        upstream_service_type = ServiceType.objects.filter(name=service_type_name).first()
        if upstream_service_type is None:
            error_msg = f"Migrations are not allowed for services of type {service_metadata['service_type']}"
            self.stderr.write(f"Skipping service {service_slug}: {error_msg}")
            return False, error_msg

        if upstream_service_type.name != service_api.service_cluster.service_type.name:
            error_msg = (
                f"Service type mismatch: "
                f"Service is configured as type {service_api.service_cluster.service_type.name}, "
                f"but the server is reporting type {upstream_service_type.name}"
            )
            self.stderr.write(f"Skipping service {service_slug}: {error_msg}")
            return False, error_msg

        service_api.service_cluster.service_id = self.upstream_service_id
        service_api.service_cluster.save()

        self.stdout.write(
            f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway"
        )

        self.migrate_controller_admin()

        for r_type in self.resource_types_to_migrate.keys():
            # Can I capture the team mapping here?
            self.migrate_resource(r_type, service_slug)

        # then pass it along
        self.migrate_user_role_assignments(service_slug, service_type_name)

        self.stdout.write(f"Completed migration for service: {service_slug}")
        return True, None

    def get_new_resource_name(
        self,
        name: str,
        unique_filter_kwargs: Dict[str, Any],
        local_resource_model: Type[models.Model],
        resource_type_name_field: str,
        service_slug: str,
    ) -> str:
        """
        Generate a unique name for a resource that doesn't conflict with existing resources.

        When a resource name conflicts with an existing resource in the Gateway, this method
        generates a new name by prefixing with the service slug and adding a numeric suffix
        if needed to ensure uniqueness.

        Args:
            name: Original resource name from upstream service
            unique_filter_kwargs: Filter parameters used to check uniqueness
            local_resource_model: Django model class for the resource type
            resource_type_name_field: Field name used for the resource name

        Returns:
            A unique name that doesn't conflict with existing resources

        Example:
            If 'my-org' exists, will return 'service_my-org' or 'service_my-org1'
        """
        original_name = f'{service_slug}_{name}'
        name = original_name

        filter_kwargs = unique_filter_kwargs.copy()
        filter_kwargs[resource_type_name_field] = name

        counter = 1
        while local_resource_model.objects.filter(**filter_kwargs).exists():
            name = original_name + str(counter)
            filter_kwargs[resource_type_name_field] = name
            counter += 1

        return name

    def create_user_migration_entry(self, user: Resource, initial_data: Dict[str, Any], additional_data: Dict[str, Any]) -> None:
        """
        Create migration metadata entries for a migrated user.

        This method creates records to track the migration of a user from an upstream
        service, including their authentication providers and legacy auth data.

        Args:
            user: Resource object representing the migrated user
            initial_data: Basic user data (username, etc.)
            additional_data: Extended user data including social auth information

        Note:
            Creates MigratedUserMetadata and MigratedAuthenticatorMetadata records
            to preserve authentication state from the upstream service.
        """
        service_cluster = self.client.service.service_cluster
        MigratedUserMetadata.objects.create(
            user=user.content_object,
            service=service_cluster,
            original_username=initial_data["username"],
        )

        for social in additional_data["social_auth"]:
            authenticator_meta, _ = MigratedAuthenticatorMetadata.objects.get_or_create(
                type=MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO,
                django_backend=social["backend_type"],
                sso_server=social["sso_server"].rstrip("/") if social["sso_server"] else None,
                service=service_cluster,
            )

            AuthenticatorUser.objects.create(
                user=user.content_object,
                provider=authenticator_meta.authenticator,
                uid=social["uid"],
            )

        if len(additional_data["social_auth"]) == 0:
            authenticator_meta, _ = MigratedAuthenticatorMetadata.objects.get_or_create(
                type=MigratedAuthenticatorMetadata.LegacyAuthTypes.PASSWORD,
                service=service_cluster,
            )

            AuthenticatorUser.objects.create(provider=authenticator_meta.authenticator, uid=initial_data["username"], user=user.content_object)

    def migrate_controller_admin(self) -> None:
        """
        Set up controller admin authenticator for the current user if needed.

        For Controller services, if the current user doesn't have a usable password,
        this method creates a controller admin authenticator and associates it with
        the user to enable authentication.

        This is necessary because controller admin users may not have standard
        password authentication configured.
        """
        service_type = self.client.service.service_cluster.service_type

        if str(service_type) == "controller" and not self.client.user.has_usable_password():
            authenticator, _ = Authenticator.objects.get_or_create(
                type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
                defaults={"enabled": True, "name": "controller admin password"},
            )

            if not self.client.user.authenticator_users.filter(provider=authenticator).exists():
                AuthenticatorUser.objects.create(
                    user=self.client.user,
                    provider=authenticator,
                    uid=self.client.user.username,
                )

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
        """
        Used for producing updated resource data for resource that failed validation.
        """
        # if the resource is a user and there is only one validation error for email field, we can remove the field
        if resource_type_name == "shared.user" and "email" in original_resource_data.errors and len(original_resource_data.errors.keys()) == 1:
            self.stderr.write(f"Removing invalid email address \'{original_resource_data.data['email']}\' for user: {original_resource_data.data['username']}")
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
        """
        Deserializes and validates resource data using the corresponding resource serializer class
        Returns the validated resource data
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
            self.stderr.write(
                f"Resource with id '{resource_ansible_id}' of type '{resource_type_name}'"
                f" failed validation with errors: {str(original_resource_data.errors)}"
            )
            # Raising exception here to stop migration to draw attention to existence of invalid resources.
            raise RuntimeError("Stopping migration of resources because invalid, non-correctable, resource(s) were encountered.")

        upstream_resource["resource_data"] = updated_resource_data

        return updated_resource_data

    def _initialize_resource_sync_payloads(self, upstream_resource: Dict[str, Any], user_partial_migration: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Prepare payloads for creating Gateway resources and updating upstream resources.

        This method sets up the data structures needed to:
        1. Create a new resource in the Gateway
        2. Update the corresponding resource in the upstream service

        For partially migrated users, the Gateway resource retains the upstream
        service_id to indicate it's not fully migrated.

        Args:
            resource: Resource data from upstream service
            user_partial_migration: True if this is a user being partially migrated

        Returns:
            Tuple of (resource_creation_kwargs, updated_service_resource)
            - resource_creation_kwargs: Data for creating Gateway resource
            - updated_service_resource: Data for updating upstream resource
        """
        """
        Prepare the initial data payloads required to create new resource in gateway and update the resource data in the upstream service.
        If resource type is 'shared.user' and is partially migrated, its `service_id` is set to upstream's service_id
        Otherwise, resource's service_id = gateway's service_id
        Args:
         - upstream_resource (dict): complete resource object from upstream service
         - user_partial_migration(bool): True if user should be partially migrated
        Returns:
         - resource_creation_kwargs (dict): used to create new resource in gateway correspondingly
         - updated_service_resource (dict): used to update the resource on the service
        """
        resource_creation_kwargs = {}
        updated_service_resource = {}

        resource_creation_kwargs["ansible_id"] = upstream_resource["ansible_id"]

        if user_partial_migration:
            # We do not update the service_id of a user on the service, only mark is_partially_migrated to True to exclude it from the
            # while loop in migrate_resource()
            updated_service_resource["is_partially_migrated"] = True
            # The resource to be created in Gateway needs to show as unmigrated by having the original service_id
            resource_creation_kwargs["service_id"] = self.upstream_service_id
        else:
            # if current resource is not shared.user or user is not partially migrated, we update the 'service_id' to Gateway's service_id
            updated_service_resource["service_id"] = str(service_id())

        return resource_creation_kwargs, updated_service_resource

    def _reconcile_existing_resource(
        self,
        upstream_resource: Dict[str, Any],
        resource_context: Dict[str, Any],
        validated_resource_data: Dict[str, Any],
        updated_service_resource: Dict[str, Any],
        should_merge: bool,
        service_slug: str,
    ) -> Tuple[bool, Optional[Resource]]:
        """
        Handle conflicts with existing resources in the Gateway.

        This method implements the core logic for handling cases where a resource
        being migrated conflicts with an existing resource in the Gateway. It supports
        three scenarios:

        1. Same ansible_id: Update existing resource with correct service_id
        2. Merge enabled: Link upstream resource to existing Gateway resource
        3. No merge: Create new resource with unique name

        Args:
            upstream_resource: Complete resource data from upstream service
            resource_context: Static data about the resource type
            validated_resource_data: Validated resource data
            updated_service_resource: Data for updating upstream resource
            should_merge: Whether to merge with existing resources
            service_slug: API slug for the service being migrated

        Returns:
            Tuple of (create_gateway_resource, existing_resource)
            - create_gateway_resource: True if a new Gateway resource should be created
            - existing_resource: Existing Gateway resource if found, None otherwise
        """
        """
        this method compares the incoming resource against the existing local resources using a set of unique fields.
        Based on whether a match is found and whether a merge is requested, it prepares the `updated_service_resource`
        to reflect the appropriate migration or merge behavior
        Args:
         - upstream_resource (dict): complete resource object from upstream service
         - resource_context (dict): contains the static data related to the current resource item
         - validated_resource_data (dict): validated data for the incoming resource, based on its shared resource type serializer.
         - updated_service_resource (dict): used to update the resource on the service
         - should_merge (bool): True if we should merge the resource in upstream with Gateway rather than creating a new one
        Returns:
         - create_gateway_resource: True if we should create the resource in gateway, False otherwise
         - existing_resource: the existing resource if there is one, else None
        """

        resource_type = resource_context["type"]
        resource_type_name_field = resource_context["type_name_field"]
        unique_fields = resource_context["unique_fields"]
        LocalResourceModel = resource_context["LocalResourceModel"]
        create_gateway_resource = True  # default

        # find a dict of key-value pairs for the specified unique fields from validated resource data
        unique_filter_kwargs = {}
        for field_name in unique_fields:
            unique_filter_kwargs[field_name] = validated_resource_data[field_name]

        try:
            existing_resource = LocalResourceModel.objects.select_related("resource").get(**unique_filter_kwargs).resource
        except LocalResourceModel.DoesNotExist:
            return create_gateway_resource, None

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
                logger.info(f"Correcting service_id of {resource_type.name} with name {upstream_resource['name']}.")
            else:
                updated_service_resource["resource_data"] = local_data
                logger.warning(f"Updating already-merged {resource_type.name} with name {upstream_resource['name']}.")

        # case 2: merge flag is set. We only set upstream metadata and ansible_id to be the same as gateway's
        # don't set anything on the gateway
        if should_merge:
            create_gateway_resource = False
            updated_service_resource.update(
                {
                    "ansible_id": existing_resource.ansible_id,
                    "resource_data": local_data,
                }
            )
            logger.warning(f"Merging {resource_type.name} with conflicting name {upstream_resource['name']}.")

        # case 3: different ansible_id and not merging. We are not correcting the service-side of the same resource.
        # We change the name of the resource and update it on the upstream service
        # Create a new resource in the Gateway with the updated name
        elif str(existing_resource.ansible_id) != resource_ansible_id:
            new_name = self.get_new_resource_name(upstream_resource["name"], unique_filter_kwargs, LocalResourceModel, resource_type_name_field, service_slug)
            upstream_resource["resource_data"][resource_type_name_field] = new_name
            # For users that are renamed due to conflicts, they should not be superusers
            # This prevents partially migrated users from inheriting superuser status
            # This is temporary and should be deleted after implementing https://issues.redhat.com/browse/AAP-47840 to fully merge user on migrations
            if resource_type.name == "shared.user":
                upstream_resource["resource_data"]["is_superuser"] = False
            updated_service_resource["resource_data"] = upstream_resource["resource_data"]
            logger.warning(f"Creating new {resource_type.name} with new name {upstream_resource['name']}.")

        return create_gateway_resource, existing_resource

    def _get_filtered_resources(self, filters: Dict[str, Any], resource_type_name: str) -> List[Dict[str, Any]]:
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
        """
        Retrieves and filters resources for a given resource type.
        """
        data = self.client.list_resources(filters=filters).json()
        self.stdout.write(f"Items remaining: {data['count']}")
        results = data['results']
        # As special case exclude the system user, since Gateway excludes this in its own resources
        if resource_type_name == 'shared.user':
            # SYSTEM_USERNAME can theoretically vary by service
            # Currently, the system username is None in controller, and in hub and eda it's the same as gateway's,
            # If Hub and EDA system username is updated to != gateway's, we are migrating it too and we should avoid it
            results = [res for res in results if res['name'] != settings.SYSTEM_USERNAME]
        return results

    def _process_and_migrate_resource_item(self, upstream_resource_item: Dict[str, Any], resource_context: Dict[str, Any], service_slug: str) -> None:
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
            service_slug: API slug for the service being migrated

        Note:
            All operations are wrapped in a database transaction to ensure
            consistency between Gateway and upstream service updates.
        """
        """
        Carries out migration logic for an individual resource item, and
        then implement the migration by creating or updating a Gateway resource, and updating the upstream resource in a single database transaction
        Args:
        - upstream_resource_item (dict): the data for a single resource item, which is acquired from the GWResourceAPI
        - resource_context (dict): contains the static data related to the current resource item
        """
        resource_ansible_id = upstream_resource_item["ansible_id"]
        resource_type = resource_context["type"]

        # Currently, we're making a GET request to the upstream service for every single resource
        # This implementation is non-optimal. However, we can leave this as is for now
        # since there is an ongoing initiative to rework the migration process

        # Fetch the complete resource data from the upstream service (Controller/Hub/EDA)
        # This contains the full API response structure with metadata, ansible_id, service_id, resource_data, additional_data, etc.
        upstream_resource = self.client.get_resource(resource_ansible_id).json()
        self.stdout.write(f"upstream_resource {upstream_resource}")

        # Extract and validate the core resource data from the upstream response
        # This is the clean, validated resource data ready for Gateway use
        validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

        # Sync superuser flags for user resources
        if resource_context["type_name"] == "shared.user":
            upstream_resource = self._sync_user_superuser_flag(upstream_resource, validated_resource_data)
            # Re-validate after potential superuser flag changes
            validated_resource_data = self._deserialize_and_validate_resource_data(upstream_resource, resource_context["type_serializer"])

        # 'shared.user' type is treated differently
        # If the user being migrated is not the current user (admin user), we need to check if we should partially migrate the user
        user_partial_migration = bool(resource_context["type_name"] == "shared.user" and upstream_resource["name"] != self.client.user.username)

        resource_creation_kwargs, updated_service_resource = self._initialize_resource_sync_payloads(upstream_resource, user_partial_migration)

        # should_merge indicates the final merge action.
        # The default is the value passed into the merge option when running the command, which is True to indicate we are merging the admin user
        should_merge = resource_context["merge_option"] if not user_partial_migration else False

        # handles case with existing resource and figure out if we should create a new resource in gateway or not
        create_gateway_resource, existing_resource = self._reconcile_existing_resource(
            upstream_resource, resource_context, validated_resource_data, updated_service_resource, should_merge, service_slug
        )

        # Run this as a transaction so that if the REST call to update the resource on the service fails
        # we also rollback any database changes that were made on the Gateway.
        with transaction.atomic():
            # determine the resource to use in Gateway
            if create_gateway_resource:
                gw_resource = Resource.create_resource(resource_type, upstream_resource["resource_data"], **resource_creation_kwargs)
            else:
                gw_resource = existing_resource

            # Connect legacy authentication for users, but do not connect any for the superuser
            if user_partial_migration:
                # Create the migration entry only if we are actually creating a gateway
                # resource.  If we aren't we're updating an already existing user on
                # the service.
                if create_gateway_resource:
                    self.create_user_migration_entry(gw_resource, validated_resource_data, upstream_resource["additional_data"])

            self.client.update_resource(resource_ansible_id, ResourceRequestBody(**updated_service_resource), partial=True)

    """
    Before migration, we need to send requests to upstream services and acquire resources data.
    Then, to migrate, we need to do one of three things:
    - If the resource exists in the Gateway and merge is set to true: Don't change anything in
      the gateway. Set the "ansible_id" and "service_id" on the resource in the service to
      match the Gateway's value. This indicates that the resource is managed by the Gateway
      and that the it is the same resource as the one that already exists in Gateway
    - If the resource exists in the Gateway and merge is set to false: Create a new resource
      in Gateway with a name that doesn't conflict with the existing resource in the service
      using the "ansible_id" provided by the service. Rename the existing resource on the
      service and set the "service_id" to the Gateway's ID.
    - If the resource doesn't exist in Gateway: Create a new resource in Gateway using the
      data from the resource in the service, including the "ansible_id". Set the "service_id"
      of the resource in the service to match the Gateway's ID.

    Note that in all cases we're setting the "service_id" on the resource in the service to
    match the Gateway's ID. This indicates to the service and to the Gateway that the resource
    is now managed externally by the Gateway.
    """

    def migrate_resource(self, resource_type_name: str, service_slug: str) -> None:
        """
        Migrate all resources of a specific type from upstream service to Gateway.

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
            service_slug: API slug for the service being migrated

        Note:
            Resources are migrated in dependency order: organizations first,
            then teams (which depend on organizations), then users.
        """
        """
        Get a list of resources from the upstream service and add them to the Gateway.
        Build a `resource_context` dict containing the data related to the current resource type to avoid code duplication
        Keys:
        - type (ResourceType instance): the object associated with the current resource.
        - type_name (str): name of the resource type (i.e: 'shared.user', 'shared.organization', 'shared.team')
        - type_serializer (serializer instance): used to validate and deserialize the resource data
        - type_name_field (str): the name of the field used to uniquely define the resource
        - unique_fields (list): a list of field names that together uniquely identify a resource
        - merge_option (bool): whether to merge with existing Gateway resource
        - LocalResourceModel (model class): the model class in gateway that is associated with the resource_type
                                            (i.e: Organization class for resource_type 'shared.organization')
        """
        self.stdout.write(f"Migrating data for {resource_type_name}")

        resource_type = self.resource_types_to_migrate[resource_type_name]["type"]

        resource_context = {
            "type": resource_type,
            "type_name": resource_type_name,
            "type_serializer": resource_type.serializer_class,
            "type_name_field": resource_type.get_resource_config().name_field,
            "unique_fields": self.resource_types_to_migrate[resource_type_name]["unique_fields"],
            "merge_option": self.resource_types_to_migrate[resource_type_name]["merge"],
            "LocalResourceModel": resource_type.content_type.model_class(),
        }

        # Each resource that gets updated in the Gateway will change the service ID to Gateway's (except for 'shared.user'), and
        # will cause the migrated resources to be filtered out of the server response.
        # 'shared.user' resource type can also be filtered out by setting the 'is_partially_migrated' flag to true
        # Thus, we don't need to deal with pagination here. We just keep calling the list view until the filter returns no items.
        api_call_filters = {
            "service_id": self.upstream_service_id,
            "is_partially_migrated": "false",
            "content_type__resource_type__name": resource_type_name,
        }

        # Following 'while True' loop is used because we are modifying the list as we go through it.
        # By changing the service ID or setting partially migrated, we are removing items from the filter,
        # so this doesn't actually use pagination. It just keeps loading the same filter over and over
        # until nothing is left to migrate.
        while True:
            results = self._get_filtered_resources(api_call_filters, resource_type_name)

            if len(results) == 0:
                self.stdout.write("No more items remaining to migrate.")
                break

            for upstream_resource_item in results:
                self._process_and_migrate_resource_item(upstream_resource_item, resource_context, service_slug)
                self.stdout.write(f"upstream resource item {upstream_resource_item} resource_context {resource_context}")

    def _sync_user_superuser_flag(self, upstream_resource: Dict[str, Any], validated_resource_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sync superuser flags between services according to the following requirements.

        Controller → Gateway: If Controller user is superuser, promote Gateway user to superuser
        Gateway → Hub/EDA: Sync Gateway superuser status to upstream service

        Args:
            upstream_resource: Complete resource data from upstream service
            validated_resource_data: Validated resource data

        Returns:
            Updated resource data with correct is_superuser flag
        """
        service_type = self.client.service.service_cluster.service_type.name
        username = validated_resource_data["username"]
        upstream_is_superuser = validated_resource_data.get("is_superuser", False)

        if service_type == DefaultServiceType.CONTROLLER.value:
            # Controller → Gateway: Promote Gateway user if Controller user is superuser
            if upstream_is_superuser:
                try:
                    gateway_user = User.objects.get(username=username)
                    if not gateway_user.is_superuser:
                        gateway_user.is_superuser = True
                        gateway_user.save()
                        self.stdout.write(f"Promoted Gateway user '{username}' to superuser based on Controller")
                except User.DoesNotExist:
                    # New user will be created with Controller's superuser status
                    self.stdout.write(f"New user '{username}' will be created with superuser status from Controller")

                # Ensure the resource data reflects superuser status
                upstream_resource["resource_data"]["is_superuser"] = True

        elif service_type in [DefaultServiceType.HUB.value, DefaultServiceType.EDA.value]:
            # Hub/EDA users should only be superusers if they already exist in Gateway as superusers
            # This prevents auto-synced superuser users from maintaining superuser status during migration
            self.stdout.write(f"Checking superuser status for user '{username}'")

            self.stdout.write(f"Is admin user in {service_type}: {upstream_is_superuser}")

            should_be_superuser = False

            # Only set superuser if user already exists in Gateway as a superuser
            try:
                gateway_user = User.objects.get(username=username)
                self.stdout.write(f"Gateway user exists: {gateway_user}")
                should_be_superuser = gateway_user.is_superuser
                self.stdout.write(f"Gateway user is superuser: {should_be_superuser}")
            except User.DoesNotExist:
                # New users from Hub/EDA should not be superusers
                should_be_superuser = False
                self.stdout.write("Gateway user does not exist, will not be superuser")

            upstream_resource["resource_data"]["is_superuser"] = should_be_superuser

            if upstream_is_superuser != should_be_superuser:
                action = "promoted to" if should_be_superuser else "demoted from"
                reason = "exists in Gateway as superuser" if should_be_superuser else "does not exist in Gateway as superuser"
                self.stdout.write(f"User '{username}' {action} superuser in {service_type} ({reason})")

        return upstream_resource

    def _ensure_superuser_consistency(self, service_apis: List[ServiceAPIRoute], user: AbstractUser) -> None:
        """
        Validate and correct superuser consistency across all services after migration.

        Requirements:
        1. Superusers in Controller and Gateway should match exactly
        2. Superusers in EDA/Hub that are not in Gateway should be demoted

        Args:
            service_apis: List of service APIs that were processed
            user: User to perform API calls as
        """
        self.stdout.write("\n=== Validating superuser consistency ===")

        # Get all Gateway superusers
        gateway_superusers = set(User.objects.filter(is_superuser=True).values_list('username', flat=True))
        self.stdout.write(f"Gateway superusers: {sorted(gateway_superusers)}")

        controller_api = None
        hub_eda_apis = []

        for service_api in service_apis:
            service_type = service_api.service_cluster.service_type.name
            if service_type == DefaultServiceType.CONTROLLER.value:
                controller_api = service_api
            elif service_type in [DefaultServiceType.HUB.value, DefaultServiceType.EDA.value]:
                hub_eda_apis.append(service_api)

        # Validate Controller ↔ Gateway consistency
        if controller_api:
            self._validate_controller_gateway_superusers(controller_api, gateway_superusers, user)

        # Demote superusers in Hub/EDA that are not superusers in Gateway
        for service_api in hub_eda_apis:
            self._demote_extra_superusers(service_api, gateway_superusers, user)

    def _validate_controller_gateway_superusers(self, controller_api: ServiceAPIRoute, gateway_superusers: set, user: AbstractUser) -> None:
        """
        Validate that Controller and Gateway superusers match exactly.

        After migration, all resources have Gateway's service_id, so this validation
        checks that the shared resource registry has consistent superuser flags.
        """
        client = GWResourceAPIClient(controller_api, raise_if_bad_request=True, user=user)

        # Get all users from the shared resource registry (no service_id filter since
        # after migration all resources have Gateway's service_id)
        filters = {
            "content_type__resource_type__name": "shared.user",
        }

        controller_superusers = set()
        page = 1

        while True:
            data = client.list_resources(filters={**filters, "page": page}).json()

            for user_item in data["results"]:
                user_detail = client.get_resource(user_item["ansible_id"]).json()
                username = user_detail["resource_data"]["username"]
                resource_data = user_detail["resource_data"]

                # Check if user is actually a superuser
                if resource_data.get("is_superuser", False):
                    controller_superusers.add(username)

            if not data.get("next"):
                break
            page += 1

        self.stdout.write(f"Controller superusers: {sorted(controller_superusers)}")

        # Check for mismatches
        gateway_only = gateway_superusers - controller_superusers
        controller_only = controller_superusers - gateway_superusers

        if gateway_only:
            self.stderr.write(f"Error: Users are superusers in Gateway but not Controller: {sorted(gateway_only)}")
            raise CommandError(f"Superuser inconsistency detected: Users {sorted(gateway_only)} are superusers in Gateway but not in Controller")

        if controller_only:
            self.stderr.write(f"Error: Users are superusers in Controller but not Gateway: {sorted(controller_only)}")
            raise CommandError(f"Superuser inconsistency detected: Users {sorted(controller_only)} are superusers in Controller but not in Gateway")

        if not gateway_only and not controller_only:
            self.stdout.write("✓ Controller and Gateway superusers are consistent")

    def _demote_extra_superusers(self, service_api: ServiceAPIRoute, gateway_superusers: set, user: AbstractUser) -> None:
        """Demote superusers in Hub/EDA that are not superusers in Gateway."""
        service_type = service_api.service_cluster.service_type.name
        client = GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        filters = {
            "service_id": service_api.service_cluster.service_id,
            "content_type__resource_type__name": "shared.user",
        }

        demoted_users = []
        page = 1
        while True:
            data = client.list_resources(filters={**filters, "page": page}).json()

            for user_item in data["results"]:
                user_detail = client.get_resource(user_item["ansible_id"]).json()
                username = user_detail["resource_data"]["username"]
                is_superuser = user_detail["resource_data"].get("is_superuser", False)

                # If user is superuser in service but not in Gateway, demote them
                if is_superuser and username not in gateway_superusers:
                    updated_resource_data = user_detail["resource_data"].copy()
                    updated_resource_data["is_superuser"] = False

                    update_payload = {"resource_data": updated_resource_data}
                    client.update_resource(user_item["ansible_id"], ResourceRequestBody(**update_payload), partial=True)

                    demoted_users.append(username)
                    self.stdout.write(f"Demoted user '{username}' from superuser in {service_type}")

            if not data.get("next"):
                break
            page += 1

        if demoted_users:
            self.stdout.write(f"Demoted {len(demoted_users)} users from superuser in {service_type}: {sorted(demoted_users)}")
        else:
            self.stdout.write(f"✓ No extra superusers found in {service_type}")

    def _lookup_gateway_user(self, assignment: Dict[str, Any]) -> AbstractUser:
        """
        Look up a gateway user corresponding to a service user.

        This method attempts to find a gateway user using either the service user's
        ansible_id (preferred) or username (fallback). It provides detailed logging
        and consistent error handling.

        Args:
            assignment: a Dict containing serialized assignment data from a
                user_role_assignment, including the 'user_ansible_id'
                and 'summary_fields' elements of a single user assignment.
        Returns:
            Gateway user matching the user referenced by the assignment data

        Raises:
            RuntimeError: If the user cannot be found in the gateway database
        """
        service_user_ansible_id = assignment.get('user_ansible_id', None)
        service_user = assignment.get('summary_fields', {}).get('user', None)

        try:
            if service_user_ansible_id:
                self.stdout.write(f"Role assignment references user's ansible_id '{service_user_ansible_id}', preferring ansible_id for gateway user lookup.")
                gateway_user = Resource.objects.get(ansible_id=service_user_ansible_id).content_object
            else:
                self.stdout.write(
                    f"Role assignment does not reference user's ansible_id, falling back to username '{service_user.get('username')}' for gateway user lookup."
                )
                gateway_user = User.objects.get(username=service_user.get('username'))
        except Exception:
            self.stderr.write(f"User {service_user.get('username')} not found in gateway database.")
            raise RuntimeError("Stopping migration of user role assignments because assigned user is missing in gateway database.")

        return gateway_user

    def _lookup_gateway_content_object(self, assignment: Dict[str, Any]) -> Optional[Any]:
        """
        Look up a gateway content object corresponding to a service content object.

        This method attempts to find a gateway content object using either the service object's
        ansible_id (preferred) or by looking up the object by name and content type (fallback).
        If no object ID is provided, it returns None (indicating service-wide assignment).

        Args:
            assignment: a Dict containing serialized assignment data from a
                user_role_assignment, including the service_content_object details

        Returns:
            Gateway content object (Team or Organization), or None if assignment is global.

        Raises:
            RuntimeError: If the object cannot be found in the gateway database
        """
        service_content_object_ansible_id = assignment.get('object_ansible_id', None)
        service_content_object_id = assignment.get('object_id', None)
        service_content_object = assignment.get('summary_fields', {}).get('content_object', {})

        try:
            if service_content_object_ansible_id:
                self.stdout.write(
                    f"Role assignment references object's ansible_id '{service_content_object_ansible_id}'. "
                    + "preferring ansible_id for gateway object lookup."
                )
                gateway_content_object = Resource.objects.get(ansible_id=service_content_object_ansible_id).content_object
            elif service_content_object_id:
                # We have an object id, so we know this assignment is for a specific object. However, that object id is not relevant to gateway,
                # it's the remote id of the object in the service's database. So we need to resolve the object id in gateway's database.
                self.stdout.write(f"Fetching ResourceType by {assignment.get('content_type')} with name {service_content_object.get('name')}")
                resource_type = ResourceType.objects.get(name=assignment.get('content_type'))
                # TODO: What if the resource is a Team? we need to know what org it belongs to.
                gateway_content_object = resource_type.content_type.get_object_for_this_type(name=service_content_object.get('name'))
            else:
                # 'content_object' is None. That's valid and means this role assignment applies to the entire service (e.g.  not a specific team or org)
                gateway_content_object = None
        except Exception:
            self.stderr.write(f"Object {assignment['content_type']} with name {service_content_object['name']} not found in gateway database.")
            raise RuntimeError("Stopping migration of user role assignments because assigned user is missing in gateway database.")

        return gateway_content_object

    def _lookup_role_definition(self, service_slug: str, assignment: Dict[str, Any]):
        """
        For a service-specific role definition name in the assignment (e.g. Controller Team Member),
        return the corresponding RoleDefinition for Platform
        """

        role_definition_name = assignment.get('summary_fields', {}).get('role_definition', {}).get('name', None)  # e.g. 'Organization Admin'
        self.stdout.write(f"Fetching gateway role definition '{role_definition_name}. RoleDefinition count: {RoleDefinition.objects.count()}'")
        role_definition = RoleDefinition.objects.get(name=role_definition_name)
        self.stdout.write(f"Fetched gateway role definition '{role_definition}")
        return role_definition

    @staticmethod
    def _format_fetched_assignment_for_logging(assignment: Dict[str, Any]) -> str:
        summary_fields = assignment.get('summary_fields', {})
        return (
            f"username: {summary_fields.get('user', {}).get('username')}, "
            f"object_type: {assignment.get('content_type')}, "
            f"object_name: {summary_fields.get('content_object', {}).get('name')}, "
            f"role_definition_name: {summary_fields.get('role_definition', {}).get('name')}"
        )

    def _format_migrated_assignment_for_logging(self, role_user_assignment: RoleUserAssignment) -> str:
        return (
            f"username: {role_user_assignment.user.username}, "
            f"object_id: {role_user_assignment.object_id}, "
            f"role_definition_name: {role_user_assignment.role_definition.name}"
        )

    def _get_role_definitions_to_migrate(self, service_type: str) -> List[str]:
        ROLE_DEFINITION_FILTERS = {
            # For controller, we want to migrate these 4 managed roles
            DefaultServiceType.CONTROLLER.value: ['Platform Auditor', 'Organization Admin', 'Organization Member', 'Team Admin', 'Team Member'],
            # For hub, we want to migrate this single managed role
            DefaultServiceType.HUB.value: ['Team Member'],
        }
        return ROLE_DEFINITION_FILTERS.get(service_type, [])

    def _fetch_role_user_assignments(self, service_slug: str, service_type_name: str) -> Iterator[Dict[str, Any]]:
        """
        Fetch all role_user_assignments from the service with pagination
        """
        role_definitions_to_migrate = self._get_role_definitions_to_migrate(service_type_name)
        if not role_definitions_to_migrate:
            # Nothing to fetch, bail out now
            self.stdout.write(f"No role definitions to migrate for {service_slug} of type {service_type_name}, skipping...")
            return

        page = 1
        total_count = None  # we will check this on each page to see if anything changed
        while True:
            self.stdout.write(f"Fetching page {page} of role_user_assignments from {service_slug}")
            params = {'page': page, 'role_definition__name__in': ','.join(role_definitions_to_migrate)}
            # This code successfully handles pagination, but API ignores the page_size parameter
            # Note: This private method call in GWResourceAPIClient is temporary and will be obsoleted by AAP-48396
            json_response = self.client._make_request("get", '../role_user_assignments/', params=params).json()
            if total_count is None:
                total_count = json_response.get('count', 0)
            elif total_count != json_response.get('count', 0):
                self.stderr.write(f"Error: RoleUserAssignments count changed from {total_count} to {json_response.get('count', 0)}")
                raise RuntimeError("RoleUserAssignments count changed during migration")
            for assignment in json_response.get('results', []):
                yield assignment
            if not json_response.get('next'):
                break
            page += 1

    def migrate_user_role_assignments(self, service_slug: str, service_type_name: str) -> None:
        """
        Migrates the role_user_assignments from an individual service to platform-level role assignments

        This method must run after Organizations/Teams/Users have been migrated. It migrates the role assignments,
        so the subjects and objects of those assignments must exist.

        It performs this migration by:

        1. Querying the service's /role_user_assignments API for assignments corresponding to the known
           list of Role Definitions (Organization Admin, Team Member, etc.) (pagination!)
        2. Looking up the local (aap-gateway) user referenced in each assignment (do some grouping here)
        3. Looking up the local (aap-gateway) role definition corresponding to the service definition (Controller Team Member -> Team Member)
        4. Creating a RoleUserAssignment binding the gateway user to the gateway object and gateway role definition (or ignoring if it exists)
        """

        self.stdout.write(f"Migrating RoleUserAssignments from {service_slug} of type {service_type_name}")
        assignments = self._fetch_role_user_assignments(service_slug, service_type_name)
        self.stdout.write(f"Fetched role_user_assignments from {service_slug}")

        for assignment in assignments:
            self.stdout.write(f"Processing assignment in service {service_slug}: {self._format_fetched_assignment_for_logging(assignment)}")

            # Lookup the role definition, user, and object
            gateway_role_definition = self._lookup_role_definition(service_slug, assignment)
            gateway_user = self._lookup_gateway_user(assignment)
            gateway_content_object = self._lookup_gateway_content_object(assignment)

            # Create the role user assignment in gateway
            if gateway_content_object:
                role_user_assignment = gateway_role_definition.give_permission(gateway_user, gateway_content_object)
            else:
                role_user_assignment = gateway_role_definition.give_global_permission(gateway_user)
            message = "Created role user assignment"
            self.stdout.write(f"{message}: {self._format_migrated_assignment_for_logging(role_user_assignment)}")  # type: ignore
