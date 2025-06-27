import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple, Type

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from requests.exceptions import HTTPError

from aap_gateway_api.models import DefaultServiceType, MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, ServiceType
from aap_gateway_api.utils.resources_client import GWResourceAPIClient

logger = logging.getLogger('aap_gateway_api.management.commands.migrate_service_data')
User = get_user_model()


class Command(BaseCommand):
    """
    Django management command for migrating organizations, teams, and users from existing AAP
    installations into the gateway.

    This command facilitates the migration of resources from upstream Ansible services (Controller,
    Hub, EDA) into the gateway's resource registry system. It handles:

    - Organizations: Can be merged or kept separate based on configuration
    - Teams: Can be merged or kept separate based on configuration
    - Users: Always merged for the admin user, others are partially migrated

    The migration process involves:
    1. Connecting to the upstream service via API
    2. Fetching resource data from the upstream service
    3. Creating or updating resources in the gateway
    4. Updating upstream resources with Gateway service IDs

    Important: Users are never fully migrated - only the admin user is merged,
    while other users are partially migrated to preserve authentication state.
    """

    help = """Migrate Organizations and teams from existing AAP installations into the gateway.

    There is no option to control merging of users, because users are never migrated.
    The exception is that the provided --username, which will be merged."""

    def add_arguments(self, parser) -> None:
        """
        Add command line arguments for the migrate_service_data command.

        Args:
            parser: ArgumentParser instance for adding command arguments
        """
        services = ServiceAPIRoute.objects.exclude(service_cluster__service_type__name=DefaultServiceType.GATEWAY.value).values_list("api_slug", flat=True)

        parser.add_argument("--api-slug", type=str, help="API slug for the ServiceAPIRoute that you wish to migrate.", choices=services, required=True)
        parser.add_argument("--username", type=str, help="Username for the gateway user to use on the request. Must be an admin user.", required=True)
        parser.add_argument(
            "--merge-teams",
            type=bool,
            help=(
                "If true, teams with the same names on different services will be combined. NOTE: this can potentially lead to"
                " escalation of privileges, as users who are in Team A in service A, will also end up in Team A on service B, even "
                "if they weren't before."
            ),
            default=False,
        )
        parser.add_argument(
            "--merge-organizations",
            type=bool,
            help=(
                "If true, organizations with the same names on different services will be combined. NOTE: this can potentially lead to"
                " escalation of privileges, as users and resources who are in Org A in service A, will also end up in Org A on service "
                "B, even if they weren't before."
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
        self.service_slug = options["api_slug"]
        merge_teams = options["merge_teams"]
        merge_organizations = options["merge_organizations"]
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
            service_api = ServiceAPIRoute.objects.get(api_slug=self.service_slug)
        except ServiceAPIRoute.DoesNotExist:
            raise CommandError(f"Service with API slug {self.service_slug} does not exist.")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Username {username} does not exist")

        # TODO: switch user out for _system. Need to get more fine grained permissions in resources
        # api merged first.
        self.client = GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        try:
            self.stdout.write("Starting migration")

            self.stdout.write("Getting service metadata")
            service_metadata = self.client.get_service_metadata().json()

            self.upstream_service_id = service_metadata["service_id"]
            # Preserve coersion of awx -> controller and galaxy -> hub
            if service_metadata["service_type"].casefold() == "awx".casefold():
                service_type_name = DefaultServiceType.CONTROLLER.value
            elif service_metadata["service_type"].casefold() == "galaxy".casefold():
                service_type_name = DefaultServiceType.HUB.value
            else:
                service_type_name = service_metadata["service_type"]
            upstream_service_type = ServiceType.objects.filter(name=service_type_name).first()
            if upstream_service_type is None:
                raise CommandError(f"Migrations are not allowed for services of type {service_metadata['service_type']}")

            if upstream_service_type.name != service_api.service_cluster.service_type.name:
                raise CommandError(
                    f"Service type mismatch: Service {self.service_slug} is configured as type {service_api.service_cluster.service_type.name},"
                    f" but the server is reporting type {upstream_service_type.name}"
                )

            service_api.service_cluster.service_id = self.upstream_service_id
            service_api.service_cluster.save()

            self.stdout.write(
                f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway"
            )

            self.migrate_controller_admin()

            for r_type in self.resource_types_to_migrate.keys():
                self.migrate_resource(r_type)

            self.stdout.write("Done")

        except HTTPError as e:
            raise CommandError("Bad API request: " + str(e))

    def get_new_resource_name(
        self, name: str, unique_filter_kwargs: Dict[str, Any], LocalResourceModel: Type[models.Model], resource_type_name_field: str
    ) -> str:
        """
        Generate a unique name for a resource that doesn't conflict with existing resources.

        When a resource name conflicts with an existing resource in the gateway, this method
        generates a new name by prefixing with the service slug and adding a numeric suffix
        if needed to ensure uniqueness.

        Args:
            name: Original resource name from upstream service
            unique_filter_kwargs: Filter parameters used to check uniqueness
            LocalResourceModel: Django model class for the resource type
            resource_type_name_field: Field name used for the resource name

        Returns:
            A unique name that doesn't conflict with existing resources

        Example:
            If 'my-org' exists, will return 'service_my-org' or 'service_my-org1'
        """
        original_name = f'{self.service_slug}_{name}'
        name = original_name

        filter_kwargs = unique_filter_kwargs.copy()
        filter_kwargs[resource_type_name_field] = name

        counter = 1
        while LocalResourceModel.objects.filter(**filter_kwargs).exists():
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

    def _deserialize_and_validate_resource_data(self, resource: Dict[str, Any], resource_serializer: Any) -> Dict[str, Any]:
        """
        Deserialize and validate resource data using the appropriate serializer.

        This method validates resource data from the upstream service and attempts
        to fix common validation errors. If validation fails and cannot be fixed,
        the migration is halted.

        Args:
            resource: Resource data from upstream service
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
        original_resource_data = resource_serializer(data=resource["resource_data"])
        resource_type_name = resource['resource_type']
        resource_ansible_id = resource['ansible_id']

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

        resource["resource_data"] = updated_resource_data

        return updated_resource_data

    def _initialize_resource_sync_payloads(self, resource: Dict[str, Any], user_partial_migration: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Prepare payloads for creating Gateway resources and updating upstream resources.

        This method sets up the data structures needed to:
        1. Create a new resource in the gateway
        2. Update the corresponding resource in the upstream service

        For partially migrated users, the gateway resource retains the upstream
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
         - resource (dict): is the resource object being migrated
         - user_partial_migration(bool): True if user should be partially migrated
        Returns:
         - resource_creation_kwargs (dict): used to create new resource in gateway correspondingly
         - updated_service_resource (dict): used to update the resource on the service
        """
        resource_creation_kwargs = {}
        updated_service_resource = {}

        resource_creation_kwargs["ansible_id"] = resource["ansible_id"]

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
        resource: Dict[str, Any],
        resource_context: Dict[str, Any],
        validated_resource_data: Dict[str, Any],
        updated_service_resource: Dict[str, Any],
        should_merge: bool,
    ) -> Tuple[bool, Optional[Resource]]:
        """
        Handle conflicts with existing resources in the gateway.

        This method implements the core logic for handling cases where a resource
        being migrated conflicts with an existing resource in the gateway. It supports
        three scenarios:

        1. Same ansible_id: Update existing resource with correct service_id
        2. Merge enabled: Link upstream resource to existing Gateway resource
        3. No merge: Create new resource with unique name

        Args:
            resource: Resource data from upstream service
            resource_context: Static data about the resource type
            validated_resource_data: Validated resource data
            updated_service_resource: Data for updating upstream resource
            should_merge: Whether to merge with existing resources

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
         - resource (dict): is the resource object being migrated
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
        resource_ansible_id = resource['ansible_id']
        local_data = resource_type.serializer_class(existing_resource.content_object).data
        incoming_data = resource.get("resource_data", {})

        # case 1: the JWT auth classes create some items with correct ansible_id but without the service_id fully set,
        # so this will correct the service_id and possibly update the stale resource_data
        if str(existing_resource.ansible_id) == resource_ansible_id:
            create_gateway_resource = False
            updated_service_resource["service_id"] = existing_resource.service_id

            if incoming_data == local_data:
                logger.info(f"Correcting service_id of {resource_type.name} with name {resource['name']}.")
            else:
                updated_service_resource["resource_data"] = local_data
                logger.warning(f"Updating already-merged {resource_type.name} with name {resource['name']}.")

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
            logger.warning(f"Merging {resource_type.name} with conflicting name {resource['name']}.")

        # case 3: different ansible_id and not merging. We are not correcting the service-side of the same resource.
        # We change the name of the resource and update it on the upstream service
        # Create a new resource in the gateway with the updated name
        elif str(existing_resource.ansible_id) != resource_ansible_id:
            new_name = self.get_new_resource_name(resource["name"], unique_filter_kwargs, LocalResourceModel, resource_type_name_field)
            resource["resource_data"][resource_type_name_field] = new_name
            updated_service_resource["resource_data"] = resource["resource_data"]
            logger.warning(f"Creating new {resource_type.name} with new name {resource['name']}.")

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
            # See related Jira Ticket AAP-47114
            results = [res for res in results if res['name'] != settings.SYSTEM_USERNAME]
        return results

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
        resource = self.client.get_resource(resource_ansible_id).json()
        validated_resource_data = self._deserialize_and_validate_resource_data(resource, resource_context["type_serializer"])

        # 'shared.user' type is treated differently
        # If the user being migrated is not the current user (admin user), we need to check if we should partially migrate the user
        user_partial_migration = bool(resource_context["type_name"] == "shared.user" and resource["name"] != self.client.user.username)

        resource_creation_kwargs, updated_service_resource = self._initialize_resource_sync_payloads(resource, user_partial_migration)

        # should_merge indicates the final merge action.
        # The default is the value passed into the merge option when running the command, which is True to indicate we are merging the admin user
        should_merge = resource_context["merge_option"] if not user_partial_migration else False

        # handles case with existing resource and figure out if we should create a new resource in gateway or not
        create_gateway_resource, existing_resource = self._reconcile_existing_resource(
            resource, resource_context, validated_resource_data, updated_service_resource, should_merge
        )

        # Run this as a transaction so that if the REST call to update the resource on the service fails
        # we also rollback any database changes that were made on the gateway.
        with transaction.atomic():
            # determine the resource to use in Gateway
            if create_gateway_resource:
                gw_resource = Resource.create_resource(resource_type, resource["resource_data"], **resource_creation_kwargs)
            else:
                gw_resource = existing_resource

            # Connect legacy authentication for users, but do not connect any for the superuser
            if user_partial_migration:
                # Create the migration entry only if we are actually creating a gateway
                # resource.  If we aren't we're updating an already existing user on
                # the service.
                if create_gateway_resource:
                    self.create_user_migration_entry(gw_resource, validated_resource_data, resource["additional_data"])

            self.client.update_resource(resource_ansible_id, ResourceRequestBody(**updated_service_resource), partial=True)

    """
    Before migration, we need to send requests to upstream services and acquire resources data.
    Then, to migrate, we need to do one of three things:
    - If the resource exists in the gateway and merge is set to true: Don't change anything in
      the gateway. Set the "ansible_id" and "service_id" on the resource in the service to
      match the gateway's value. This indicates that the resource is managed by the gateway
      and that the it is the same resource as the one that already exists in Gateway
    - If the resource exists in the gateway and merge is set to false: Create a new resource
      in Gateway with a name that doesn't conflict with the existing resource in the service
      using the "ansible_id" provided by the service. Rename the existing resource on the
      service and set the "service_id" to the gateway's ID.
    - If the resource doesn't exist in Gateway: Create a new resource in Gateway using the
      data from the resource in the service, including the "ansible_id". Set the "service_id"
      of the resource in the service to match the gateway's ID.

    Note that in all cases we're setting the "service_id" on the resource in the service to
    match the gateway's ID. This indicates to the service and to the gateway that the resource
    is now managed externally by the gateway.
    """

    def migrate_resource(self, resource_type_name: str) -> None:
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

        Note:
            Resources are migrated in dependency order: organizations first,
            then teams (which depend on organizations), then users.
        """
        """
        Get a list of resources from the upstream service and add them to the gateway.
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

        # Each resource that gets updated in the gateway will change the service ID to Gateway's (except for 'shared.user'), and
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
                self._process_and_migrate_resource_item(upstream_resource_item, resource_context)
