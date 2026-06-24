import logging
from collections import OrderedDict
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.remote import RemoteObject
from ansible_base.resource_registry.constants import (
    SHARED_AAP_FLAG_RESOURCE_TYPE,
    SHARED_ORGANIZATION_RESOURCE_TYPE,
    SHARED_ROLE_DEFINITION_RESOURCE_TYPE,
    SHARED_TEAM_RESOURCE_TYPE,
    SHARED_USER_RESOURCE_TYPE,
)
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from ansible_base.rest_pagination.default_paginator import DEFAULT_MAX_PAGE_SIZE
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction

from aap_gateway_api.models import ServiceAPIRoute, ServiceType
from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan
from aap_gateway_api.models.service_type import DefaultServiceType, get_service_type_name
from aap_gateway_api.utils import resources_client  # this importing helps to cleanly mock
from aap_gateway_api.utils.user_migration import can_accounts_be_merged, link_account, migrate_account

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')
User = get_user_model()


class AssignmentActorType(Enum):
    TEAM = 'team'
    USER = 'user'


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

    RESOURCE_DATA_FILTERS = {"extra_fields": "resource_data"}
    BIG_PAGE_FILTERS = {"page_size": str(get_setting('RESOURCE_LIST_MAX_PAGE_SIZE', DEFAULT_MAX_PAGE_SIZE))}

    # Progress reporting step size (percentage)
    PROGRESS_STEP = 5

    # Service processing order - Controller first to establish priority for user merging
    SERVICE_TYPE_ORDER = [
        DefaultServiceType.CONTROLLER.value,
        DefaultServiceType.HUB.value,
        DefaultServiceType.EDA.value,
    ]

    help = """Migrate Organizations and teams from existing AAP installations into the gateway.

    There is no option to control merging of users, because users are never migrated.
    The exception is that the provided --username, which will be merged."""

    @staticmethod
    def _copy_console_handler_config(handler: logging.Handler) -> None:
        """Copy formatter and filters from the 'aap' logger's console handler."""
        aap_handlers = logging.getLogger('aap').handlers
        if not aap_handlers:
            return
        console_handler = aap_handlers[0]
        if console_handler.formatter:
            handler.setFormatter(console_handler.formatter)
        for f in console_handler.filters:
            handler.addFilter(f)

    def _configure_logging(self, log_file: Optional[str]) -> None:
        """
        Configure the command's logger based on --log-file.

        When a log file path is provided, attaches a StreamHandler at INFO level
        so progress messages are written with structured formatting. When omitted,
        replaces all handlers with a NullHandler so logger calls are silently
        discarded and all output goes through self.stdout only.
        """
        for handler in logger.handlers[:]:
            handler.close()
        logger.handlers.clear()
        logger.propagate = False

        if hasattr(self, '_log_file_handle') and self._log_file_handle:
            self._log_file_handle.close()
            self._log_file_handle = None

        if log_file:
            self._log_file_handle = open(log_file, 'w')
            handler = logging.StreamHandler(self._log_file_handle)
            handler.setLevel(logging.INFO)
            self._copy_console_handler_config(handler)
            logger.addHandler(handler)
            if logger.level == logging.NOTSET or logger.level > logging.INFO:
                logger.setLevel(logging.INFO)
        else:
            logger.addHandler(logging.NullHandler())

    def _log(self, msg: str, level: int) -> None:
        """
        Write a message to both stdout (returned to the caller) and the logger
        (written to --log-file when provided).

        Stdout/stderr receives the message as-is (preserving newlines for
        terminal formatting). The logger receives each non-empty line as a
        separate log record so the formatter prefix appears on every line.
        """
        if level >= logging.WARNING:
            self.stderr.write(self.style.WARNING(msg))
        else:
            self.stdout.write(msg)
        for line in msg.split('\n'):
            if line:
                logger.log(level, line)

    def _log_progress(self, label: str, processed: int, total: int) -> None:
        """
        Report migration progress when a percentage threshold is crossed.

        Emits a message at every PROGRESS_STEP% interval. Always reports a starting
        message on the first item and a 100% message on the last item. If a single
        item crosses multiple thresholds, only the highest is reported.

        Output goes through _log(), which writes to both stdout and --log-file.
        """
        msg = None

        if total == 0:
            msg = f"Migration progress [{label}]: 0 items to process"
        else:
            percent = (processed / total) * 100
            threshold = (int(percent) // self.PROGRESS_STEP) * self.PROGRESS_STEP
            last = self._progress_thresholds.get(label, -1)

            if processed >= total:
                if last < 100:
                    self._progress_thresholds[label] = 100
                    msg = f"Migration progress [{label}]: {processed}/{total} (100%)"
            elif processed == 1 and last < 0:
                self._progress_thresholds[label] = threshold
                msg = f"Migration progress [{label}]: {processed}/{total} ({threshold}%)"
            else:
                threshold = min(threshold, 100)
                if threshold > last:
                    self._progress_thresholds[label] = threshold
                    msg = f"Migration progress [{label}]: {processed}/{total} ({threshold}%)"

        if msg:
            self._log(msg, logging.INFO)

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
        parser.add_argument("--username", type=str, help="Username for the gateway user to use on the request. Must be an admin user.", required=True)
        parser.add_argument(
            "--merge-teams",
            type=bool,
            help=("[IGNORED] If true, teams with the same names on different services will be combined. This flag is now ignored and defaults to True."),
            default=True,
        )
        parser.add_argument(
            "--merge-organizations",
            type=bool,
            help=(
                "[IGNORED] If true, organizations with the same names on different services will be combined. This flag is now ignored and defaults to True."
            ),
            default=True,
        )
        parser.add_argument(
            "--log-file",
            type=str,
            help="Path to write structured log output (e.g. /proc/1/fd/1 for container logs). When omitted, progress is only written to stdout.",
            required=False,
            default=None,
        )

    def _warn_ignored_flags(self, options: dict) -> None:
        if options.get("api_slug"):
            self.stderr.write(
                self.style.WARNING("Warning: --api-slug flag is ignored. The command now processes all services with DefaultServiceType (excluding gateway).")
            )

        if "merge_teams" in options:
            self.stderr.write(self.style.WARNING("Warning: --merge-teams flag is ignored. The default value is now True."))

        if "merge_organizations" in options:
            self.stderr.write(self.style.WARNING("Warning: --merge-organizations flag is ignored. The default value is now True."))

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
        self._warn_ignored_flags(options)
        self._configure_logging(options.get("log_file"))

        if MigrateServiceDataHasRan.has_migration_completed():
            self._log("Migration has already completed. Skipping.", logging.INFO)
            return

        # Force merge options to True as per requirements
        merge_teams = True
        merge_organizations = True
        username = options["username"]

        # The order here matters. Organizations need to be migrated first.
        self.resource_types_to_migrate = OrderedDict()

        self.resource_types_to_migrate[SHARED_ORGANIZATION_RESOURCE_TYPE] = {
            "merge": merge_organizations,
            "type": ResourceType.objects.get(name=SHARED_ORGANIZATION_RESOURCE_TYPE),
            "unique_fields": [
                "name",
            ],
        }
        self.resource_types_to_migrate[SHARED_TEAM_RESOURCE_TYPE] = {
            "merge": merge_teams,
            "type": ResourceType.objects.get(name=SHARED_TEAM_RESOURCE_TYPE),
            "unique_fields": [
                "name",
                "organization",
            ],
        }
        self.resource_types_to_migrate[SHARED_USER_RESOURCE_TYPE] = {
            "merge": True,  # only indicates we merge the admin user
            "type": ResourceType.objects.get(name=SHARED_USER_RESOURCE_TYPE),
            "unique_fields": [
                "username",
            ],
        }
        self.resource_types_to_migrate[SHARED_ROLE_DEFINITION_RESOURCE_TYPE] = {
            "merge": True,  # the JWT roles are already shared effectively
            "type": ResourceType.objects.get(name=SHARED_ROLE_DEFINITION_RESOURCE_TYPE),
            "unique_fields": [
                "name",
            ],
        }
        self.resource_types_to_migrate[SHARED_AAP_FLAG_RESOURCE_TYPE] = {
            "merge": True,
            "type": ResourceType.objects.get(name=SHARED_AAP_FLAG_RESOURCE_TYPE),
            "unique_fields": [
                "name",
                "condition",
            ],
        }

        user = self._get_gateway_user(username)
        if user is None:
            raise CommandError(f"Username {username} does not exist")

        # Get all services with DefaultServiceType in exact order: controller, hub, eda
        service_apis_dict = {
            api.service_cluster.service_type.name: api
            for api in ServiceAPIRoute.objects.filter(service_cluster__service_type__name__in=self.SERVICE_TYPE_ORDER)
        }

        service_apis = [service_apis_dict[service_type] for service_type in self.SERVICE_TYPE_ORDER if service_type in service_apis_dict]

        if not service_apis:
            raise CommandError(f"No services found with expected service types: {', '.join(self.SERVICE_TYPE_ORDER)}")

        self._log(f"Found {len(service_apis)} services to migrate: {', '.join(api.api_slug for api in service_apis)}", logging.INFO)

        # For RBAC management, load in types and permissions from all other components
        failed_type_services = self.load_types_and_permissions(service_apis, user)
        if failed_type_services:
            self._log(
                f"Warning: Failed to load types/permissions from: {', '.join(failed_type_services)}. Continuing with available services.", logging.WARNING
            )

        self._services_with_count_drift = set()
        self._progress_thresholds = {}

        # Merge all partially migrated users before proceeding with migration
        self._log("\n=== Merging partially migrated users ===", logging.INFO)
        self._merge_partially_migrated_users(service_apis, user)

        # Process each service and report results
        successful_services, failed_services = self._process_all_services(service_apis, user)
        self._report_migration_summary(service_apis, user, successful_services, failed_services)

    def _process_all_services(self, service_apis: List[ServiceAPIRoute], user: AbstractUser) -> Tuple[List[str], Dict[str, str]]:
        """
        Process migration for all services, returning success/failure lists.

        Returns:
            Tuple of (successful_service_slugs, failed_services_with_errors)
            where failed_services_with_errors is a dict of {slug: error_message}
        """
        successful_services: List[str] = []
        failed_services: Dict[str, str] = {}

        total_services = len(service_apis)
        for service_idx, service_api in enumerate(service_apis, 1):
            service_slug = service_api.api_slug
            self._log(f"\n=== Processing service: {service_slug} ({service_idx}/{total_services}) ===", logging.INFO)

            try:
                success, error_msg = self._migrate_single_service(service_api, service_slug, user)
                if success:
                    successful_services.append(service_slug)
                else:
                    failed_services[service_slug] = error_msg or "Unknown error"
            except Exception as e:
                error_msg = str(e)
                self._log(f"Error migrating service {service_slug}: {error_msg}", logging.WARNING)
                failed_services[service_slug] = error_msg

        return successful_services, failed_services

    def _report_migration_summary(
        self,
        service_apis: List[ServiceAPIRoute],
        user: AbstractUser,
        successful_services: List[str],
        failed_services: Dict[str, str],
    ) -> None:
        """Report migration results and finalize state."""
        total = len(successful_services) + len(failed_services)
        self._log("\n=== Migration Summary ===", logging.INFO)
        self._log(f"Total services processed: {total}", logging.INFO)
        self._log(f"Successful migrations: {len(successful_services)}", logging.INFO)
        self._log(f"Failed migrations: {len(failed_services)}", logging.INFO)

        if successful_services:
            self._log(f"\nSuccessfully migrated services: {', '.join(successful_services)}", logging.INFO)

        # Report drift warning before any exit path so it's always visible
        if self._services_with_count_drift:
            drift_list = ', '.join(sorted(self._services_with_count_drift))
            self._log(
                f"\nWARNING: The following services had count changes during role assignment migration: {drift_list}\n"
                f"This means concurrent modifications occurred while migrating. "
                f"Please re-run the migration to ensure all role assignments are migrated.",
                logging.WARNING,
            )

        if failed_services:
            self._log("\nFailed to migrate the following services:", logging.WARNING)
            for service_slug, error in failed_services.items():
                self._log(f"  - {service_slug}: {error}", logging.WARNING)
            raise CommandError(f"Migration failed for {len(failed_services)} service(s): {', '.join(failed_services)}. See error details above.")

        self._ensure_superuser_consistency(service_apis, user)

        self._log("\n=== Re-enabling service authentication ===", logging.INFO)
        if not self._services_with_count_drift:
            MigrateServiceDataHasRan.mark_migration_completed()
            self._log("✓ Migration flag updated: Service authentication is now enabled.", logging.INFO)
        else:
            self._log("⚠ Migration flag NOT set due to count drift. Re-run to complete migration.", logging.INFO)
        self._log("\nAll services migration completed successfully!", logging.INFO)

    def load_types_and_permissions(self, service_apis, user):
        failed_services = []
        for service_api in service_apis:
            service_slug = service_api.api_slug
            try:
                client = resources_client.GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)
                big_page_filter = self.BIG_PAGE_FILTERS

                # Load types into system
                response = client.list_role_types(filters=big_page_filter)

                if response.status_code != 200:
                    raise RuntimeError(f'Service {service_slug} role types gave {response.status_code} code, data: {response.data}')

                data = response.json()

                if data['next']:
                    raise RuntimeError(f'Service {service_slug} has extra pages of types: {data}')

                DABContentType.objects.load_remote_objects(data['results'])

                # Load permissions into system, these reference the types above
                response = client.list_role_permissions(filters=big_page_filter)

                if response.status_code != 200:
                    raise RuntimeError(f'Service {service_slug} permissions gave {response.status_code} code, data: {response.data}')

                data = response.json()

                if data['next']:
                    raise RuntimeError(f'Service {service_slug} has extra pages of types: {data}')

                DABPermission.objects.load_remote_objects(data['results'], update_managed=True)
            except Exception as e:
                self._log(
                    f"Warning: Failed to load types and permissions from {service_slug}: {e}. "
                    f"Role definitions referencing this service's types will not be available until the next successful migration.",
                    logging.WARNING,
                )
                failed_services.append(service_slug)
                continue
        return failed_services

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
        self.client = resources_client.GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        self._log("Starting migration", logging.INFO)

        self._log("Getting service metadata", logging.INFO)
        service_metadata = self.client.get_service_metadata().json()

        self.upstream_service_id = service_metadata["service_id"]
        # Convert the service resource_registry type to the gateway name for the service
        # Preserve coercion of awx -> controller and galaxy -> hub
        service_type_name = get_service_type_name(service_metadata["service_type"])

        upstream_service_type = ServiceType.objects.filter(name=service_type_name).first()
        if upstream_service_type is None:
            error_msg = f"Migrations are not allowed for services of type {service_metadata['service_type']}"
            self._log(f"Skipping service {service_slug}: {error_msg}", logging.WARNING)
            return False, error_msg

        if upstream_service_type.name != service_api.service_cluster.service_type.name:
            error_msg = (
                f"Service type mismatch: "
                f"Service is configured as type {service_api.service_cluster.service_type.name}, "
                f"but the server is reporting type {upstream_service_type.name}"
            )
            self._log(f"Skipping service {service_slug}: {error_msg}", logging.WARNING)
            return False, error_msg

        service_api.service_cluster.service_id = self.upstream_service_id
        service_api.service_cluster.save()

        # No-op if legacy authenticators were already deleted on a previous run
        self.delete_legacy_authenticators()

        if self._is_service_already_synced():
            self._log(f"Service {service_slug} is already synchronized — skipping resource migration.", logging.INFO)
        else:
            self._log(
                f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway",
                logging.INFO,
            )

            for r_type in self.resource_types_to_migrate.keys():
                self.migrate_resource(r_type)

        self.migrate_role_assignments(AssignmentActorType.USER, service_slug, service_type_name)
        self.migrate_role_assignments(AssignmentActorType.TEAM, service_slug, service_type_name)

        self._log(f"Completed migration for service: {service_slug}", logging.INFO)
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

        When a resource name conflicts with an existing resource in the gateway, this method
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

    def delete_legacy_authenticators(self) -> None:
        """
        Unlinks users from legacy authenticators that are no longer needed, then deletes those authenticators.

        This method does this by -
        1. Unlinks legacy authenticators from all users (removes AuthenticatorUser entries)
        2. Deletes legacy authenticators

        Legacy authenticators include:
        - Controller admin authenticators (aap_gateway_api.authentication.authenticator_plugins.controller_admin)
        - Any other authenticators that were used for legacy SSO functionality
        """
        # List of legacy authenticator types unlink users from
        # These may have existed in previous versions but the modules may no longer exist
        legacy_authenticator_types = [
            "aap_gateway_api.authentication.authenticator_plugins.controller_admin",
            "aap_gateway_api.authentication.authenticator_plugins.legacy_sso",
            "aap_gateway_api.authentication.authenticator_plugins.legacy_password",
            "aap_gateway_api.authentication.authenticator_plugins.legacy_external_password",
        ]

        for authenticator_type in legacy_authenticator_types:
            # Find all authenticators of this type in the database
            legacy_authenticators = Authenticator.objects.filter(type=authenticator_type).values('pk', 'name')

            if not legacy_authenticators.exists():
                self._log(f"No legacy authenticators of type '{authenticator_type}' found", logging.INFO)
                continue

            self._log(f"Found {legacy_authenticators.count()} legacy authenticators of type '{authenticator_type}' to clean up", logging.INFO)

            for auth_data in legacy_authenticators:
                auth_pk = auth_data['pk']
                auth_name = auth_data['name']
                user_count = AuthenticatorUser.objects.filter(provider__pk=auth_pk).count()

                if user_count > 0:
                    self._log(f"Unlinking {user_count} users from legacy authenticator '{auth_name}'", logging.INFO)
                    AuthenticatorUser.objects.filter(provider__pk=auth_pk).delete()
                self._log(f"Deleting legacy authenticator '{auth_name}'", logging.INFO)
                Authenticator.objects.filter(pk=auth_pk).delete()
                self._log(f"Deleted legacy authenticator '{auth_name}'", logging.INFO)

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
            self._log(
                f"Resource with id '{resource_ansible_id}' of type '{resource_type_name}' failed validation with errors: {str(original_resource_data.errors)}",
                logging.WARNING,
            )
            # Raising exception here to stop migration to draw attention to existence of invalid resources.
            raise RuntimeError("Stopping migration of resources because invalid, non-correctable, resource(s) were encountered.")

        upstream_resource["resource_data"] = updated_resource_data

        return updated_resource_data

    def _initialize_resource_sync_payloads(self, upstream_resource: Dict[str, Any], user_partial_migration: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
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
            service_slug: API slug for the service being migrated

        Returns:
            - create_gateway_resource (bool): True if a new Gateway resource should be created
        """

        resource_type = resource_context["type"]
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
        """
        Retrieves and filters resources for a given resource type.
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

        # 'shared.user' type is treated differently
        # If the user being migrated is not the current user (admin user), we need to check if we should partially migrate the user
        user_partial_migration = False

        resource_creation_kwargs, updated_service_resource = self._initialize_resource_sync_payloads(upstream_resource, user_partial_migration)

        # handles case with existing resource and figure out if we should create a new resource in gateway or not
        create_gateway_resource = self._reconcile_existing_resource(upstream_resource, resource_context, validated_resource_data, updated_service_resource)

        # Run this as a transaction so that if the REST call to update the resource on the service fails
        # we also rollback any database changes that were made on the gateway.
        with transaction.atomic():
            # determine the resource to use in Gateway
            if create_gateway_resource:
                Resource.create_resource(resource_type, upstream_resource["resource_data"], **resource_creation_kwargs)

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
            service_slug: API slug for the service being migrated

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
        self._log(f"Migrating data for {resource_type_name}", logging.INFO)

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

    def _get_gateway_user(self, username: str) -> Optional[AbstractUser]:
        """Get Gateway user by username, returning None if not found."""
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            return None

    def _sync_controller_superuser(self, upstream_resource: Dict[str, Any], username: str, upstream_is_superuser: bool) -> None:
        """Promote Gateway user to superuser if Controller user is superuser."""
        if not upstream_is_superuser:
            return

        gateway_user = self._get_gateway_user(username)
        if gateway_user is None:
            self._log(f"New user '{username}' will be created with superuser status from Controller", logging.INFO)
        elif not gateway_user.is_superuser:
            gateway_user.is_superuser = True
            gateway_user.save(update_fields=['is_superuser'])
            self._log(f"Promoted Gateway user '{username}' to superuser based on Controller", logging.INFO)

        upstream_resource["resource_data"]["is_superuser"] = True

    def _sync_hub_eda_superuser(self, upstream_resource: Dict[str, Any], username: str, upstream_is_superuser: bool, service_type: str) -> None:
        """Sync superuser status from Gateway to Hub/EDA (Gateway is source of truth)."""
        self._log(f"Checking superuser status for user '{username}'", logging.INFO)
        self._log(f"Is admin user in {service_type}: {upstream_is_superuser}", logging.INFO)

        gateway_user = self._get_gateway_user(username)

        if gateway_user:
            should_be_superuser = gateway_user.is_superuser
            self._log(f"Gateway user exists: {gateway_user}", logging.INFO)
            self._log(f"Gateway user is superuser: {should_be_superuser}", logging.INFO)
        else:
            should_be_superuser = False
            self._log("Gateway user does not exist, will not be superuser", logging.INFO)

        upstream_resource["resource_data"]["is_superuser"] = should_be_superuser

        if upstream_is_superuser != should_be_superuser:
            action = "promoted to" if should_be_superuser else "demoted from"
            reason = "exists in Gateway as superuser" if should_be_superuser else "does not exist in Gateway as superuser"
            self._log(f"User '{username}' {action} superuser in {service_type} ({reason})", logging.INFO)

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
            self._sync_controller_superuser(upstream_resource, username, upstream_is_superuser)
        elif service_type in [DefaultServiceType.HUB.value, DefaultServiceType.EDA.value]:
            self._sync_hub_eda_superuser(upstream_resource, username, upstream_is_superuser, service_type)

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
        self._log("\n=== Validating superuser consistency ===", logging.INFO)

        # Get all Gateway superusers
        gateway_superusers = set(User.objects.filter(is_superuser=True).values_list('username', flat=True))
        self._log(f"Gateway superusers: {sorted(gateway_superusers)}", logging.INFO)

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
            self._ensure_controller_gateway_superusers(controller_api, gateway_superusers, user)

        # Demote superusers in Hub/EDA that are not superusers in Gateway
        for service_api in hub_eda_apis:
            self._demote_extra_superusers(service_api, gateway_superusers, user)

    def _collect_controller_superusers(self, controller_api: ServiceAPIRoute, user: AbstractUser) -> set:
        """
        Collect superuser usernames from Controller via paginated API calls.

        Iterates through all shared user resources registered in the Controller service
        and returns the set of usernames that have superuser status.

        Args:
            controller_api: ServiceAPIRoute for the Controller service
            user: User to perform API calls as

        Returns:
            Set of usernames who are superusers in Controller
        """
        client = resources_client.GWResourceAPIClient(controller_api, raise_if_bad_request=True, user=user)

        # No service_id filter since after migration all resources have Gateway's service_id
        filters = {
            "content_type__resource_type__name": SHARED_USER_RESOURCE_TYPE,
        }

        controller_superusers = set()
        page = 1

        while True:
            # No page_size override; resource_data serialization is expensive per item
            data = client.list_resources(filters={**filters, **self.RESOURCE_DATA_FILTERS, "page": page}).json()

            for user_item in data["results"]:
                resource_data = user_item["resource_data"]
                username = resource_data["username"]

                if resource_data.get("is_superuser", False):
                    controller_superusers.add(username)

            if not data.get("next"):
                break
            page += 1

        return controller_superusers

    def _ensure_controller_gateway_superusers(self, controller_api: ServiceAPIRoute, gateway_superusers: set, user: AbstractUser) -> None:
        """
        Ensure that Controller and Gateway superusers are consistent by promoting users as needed.

        This method validates superuser consistency between Controller and Gateway after migration.
        Users who are superusers in Controller but not in Gateway are automatically promoted.
        If users are missing from Gateway entirely, this indicates a migration failure.

        Args:
            controller_api: ServiceAPIRoute for the Controller service
            gateway_superusers: Set of usernames who are superusers in Gateway
            user: User to perform API calls as

        Raises:
            CommandError: If users are superusers in Controller but don't exist in Gateway
                         (indicating migration failure)
        """
        controller_superusers = self._collect_controller_superusers(controller_api, user)

        self._log(f"Controller superusers: {sorted(controller_superusers)}", logging.INFO)

        # Check for mismatches
        controller_only = controller_superusers - gateway_superusers

        if controller_only:
            self._log(f"Found {len(controller_only)} users who are superusers in Controller but not Gateway: {sorted(controller_only)}", logging.INFO)
            # Promote these users to superuser in Gateway
            missing_users = []
            for username in controller_only:
                gateway_user = self._get_gateway_user(username)
                if gateway_user is None:
                    missing_users.append(username)
                    continue
                gateway_user.is_superuser = True
                gateway_user.save()
                self._log(f"Promoted Gateway user '{username}' to superuser to match Controller status", logging.INFO)

            if missing_users:
                self._log(f"Error: Users {sorted(missing_users)} are superusers in Controller but don't exist in Gateway", logging.WARNING)
                raise CommandError(f"Migration failure detected: Users {sorted(missing_users)} should have been migrated but are missing from Gateway")

        else:
            self._log("✓ Controller and Gateway superusers are consistent", logging.INFO)

    def _demote_extra_superusers(self, service_api: ServiceAPIRoute, gateway_superusers: set, user: AbstractUser) -> None:
        """Demote superusers in Hub/EDA that are not superusers in Gateway."""
        service_type = service_api.service_cluster.service_type.name
        client = resources_client.GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        filters = {
            "service_id": str(service_id()),
            "content_type__resource_type__name": SHARED_USER_RESOURCE_TYPE,
        }

        demoted_users = []
        page = 1
        while True:
            # No page_size override; resource_data serialization is expensive per item
            data = client.list_resources(filters={**filters, **self.RESOURCE_DATA_FILTERS, "page": page}).json()

            for user_item in data["results"]:
                resource_data = user_item["resource_data"]
                username = resource_data["username"]
                is_superuser = resource_data.get("is_superuser", False)

                if is_superuser and username not in gateway_superusers:
                    updated_resource_data = resource_data.copy()
                    updated_resource_data["is_superuser"] = False

                    update_payload = {"resource_data": updated_resource_data}
                    client.update_resource(user_item["ansible_id"], ResourceRequestBody(**update_payload), partial=True)

                    demoted_users.append(username)
                    self._log(f"Demoted user '{username}' from superuser in {service_type}", logging.INFO)

            if not data.get("next"):
                break
            page += 1

        if demoted_users:
            self._log(f"Demoted {len(demoted_users)} users from superuser in {service_type}: {sorted(demoted_users)}", logging.INFO)
        else:
            self._log(f"✓ No extra superusers found in {service_type}", logging.INFO)

    def _merge_partially_migrated_users(self, service_apis: List[ServiceAPIRoute], user: AbstractUser) -> None:
        """
        Merge all partially migrated users before starting the full migration.

        This optimized method gets all users from Gateway and correlates them based on prefixes,
        rather than making API calls to each service. This scales better with large user counts.

        Args:
            service_apis: List of service APIs to process
            user: User to perform API calls as
        """

        # Step 1: Get all partially migrated users from Gateway database
        # Partially migrated users have service_id != Gateway's service_id
        self._log("Finding all partially migrated users in Gateway...", logging.INFO)

        gateway_service_id = service_id()
        partially_migrated_resources = (
            Resource.objects.filter(content_type__resource_type__name=SHARED_USER_RESOURCE_TYPE)
            .exclude(service_id=gateway_service_id)
            .select_related('content_type')
        )

        total_partially_migrated_users = len(partially_migrated_resources)
        self._log(f"  Found {total_partially_migrated_users} partially migrated user resources in Gateway", logging.INFO)

        if not partially_migrated_resources:
            self._log("  No partially migrated users found in Gateway. Skipping.", logging.INFO)
            return

        # Step 2: Group users by their service types based on service_id
        self._log("Grouping users by their service types...", logging.INFO)
        service_id_to_type = {service_api.service_cluster.service_id: service_api.service_cluster.service_type.name for service_api in service_apis}

        all_users = {}  # service_type -> [(username, user_object)]
        for service_type in service_id_to_type.values():
            all_users[service_type] = []

        for resource in partially_migrated_resources:
            user_instance = resource.content_object
            username = user_instance.username

            # Determine which service this user belongs to based on service_id
            service_type = service_id_to_type.get(resource.service_id)
            if service_type:
                all_users[service_type].append((username, user_instance))
            else:
                raise RuntimeError(f"Unknown service_id {resource.service_id} for user {username}")

        for service_type, users in all_users.items():
            self._log(f"  Found {len(users)} partially migrated users from {service_type}", logging.INFO)
            for username, _ in users:
                self._log(f"    - {username}", logging.INFO)

        # Step 3: Correlate users across services by removing service prefixes
        self._log("Correlating users across services...", logging.INFO)
        user_groups = self._correlate_users_across_services(all_users)

        self._log(f"  Found {len(user_groups)} user groups to merge", logging.INFO)
        for base_username, user_accounts in user_groups.items():
            account_info = [f"{service_type}:{orig_username}" for service_type, _, orig_username in user_accounts]
            self._log(f"    - user_groups[{base_username}]: {', '.join(account_info)}", logging.INFO)

        # Step 4: Merge users with Controller user as priority
        self._log(f"Merging {total_partially_migrated_users} partially migrated users...", logging.INFO)
        total_merged = 0
        for base_username, user_accounts in user_groups.items():
            merged_count = self._merge_user_group(base_username, user_accounts)
            total_merged += merged_count

        self._log(f"Completed merging {total_merged} partially migrated users", logging.INFO)

        if total_merged != total_partially_migrated_users:
            raise RuntimeError(f"Failed to merge all partially migrated users. Merged {total_merged} out of {total_partially_migrated_users} users.")

    def _correlate_users_across_services(self, all_users: Dict[str, List[Tuple[str, AbstractUser]]]) -> Dict[str, List[Tuple[str, AbstractUser, str]]]:
        """
        Correlate users across services by identifying those that represent the same person.

        Uses logic to strip service prefixes from usernames to identify related accounts.

        Args:
            all_users: Dictionary mapping service_type to list of (username, user_object) tuples

        Returns:
            Dictionary mapping base_username to list of (service_type, user_object, original_username) tuples
        """
        user_groups = {}  # base_username -> [(service_type, user_object, original_username)]

        # Known service prefixes that may be added during 2.5 migration
        service_prefixes = ['galaxy_', 'eda_']

        for service_type in self.SERVICE_TYPE_ORDER:
            if service_type not in all_users:
                continue
            users = all_users[service_type]
            for username, user_obj in users:
                # Try to determine the base username by removing service prefixes
                base_username = username

                # Remove known service prefixes
                for prefix in service_prefixes:
                    if username.startswith(prefix):
                        base_username = username[len(prefix) :]
                        break

                if base_username not in user_groups:
                    user_groups[base_username] = []

                user_groups[base_username].append((service_type, user_obj, username))

        return user_groups

    def _merge_user_group(self, base_username: str, user_accounts: List[Tuple[str, AbstractUser, str]]) -> int:
        """
        Merge a group of user accounts that represent the same person.

        Controller user takes priority as the source of truth. Other users are merged into it.

        Args:
            base_username: The base username these accounts represent
            user_accounts: List of (service_type, user_object, original_username) tuples

        Returns:
            Number of accounts that were merged (merged_into_main_account)
        """

        service_list = ", ".join([f"{service_type}: {orig_username}" for service_type, _, orig_username in user_accounts])
        self._log(f"> Merging user group for '{base_username}' - {service_list}", logging.INFO)

        # Find Controller user to use as main account (source of truth)
        main_user = user_accounts[0]
        other_users = user_accounts[1:]

        main_service_type, main_user_obj, main_username = main_user
        self._log(f"  Using {main_service_type} user '{main_username}' as main account for '{base_username}'", logging.INFO)

        # Validate all users can be merged before starting any merges
        merge_conflicts = []
        for service_type, user_to_merge, merge_orig_username in other_users:
            if not can_accounts_be_merged(main_user_obj, user_to_merge):
                merge_conflicts.append(f"{service_type} user '{merge_orig_username}'")

        if merge_conflicts:
            self._log(f"  Cannot merge user group for '{base_username}' - conflicts detected:", logging.WARNING)
            for conflict in merge_conflicts:
                self._log(f"    - {conflict}", logging.WARNING)
            return 0

        # All users can be merged, proceed with merging
        merged_count = 0
        for service_type, user_to_merge, merge_orig_username in other_users:
            self._log(f"  Merging {service_type} user '{merge_orig_username}' into {main_service_type} user '{main_username}'", logging.INFO)
            # Perform the merge using the existing link_account function
            link_account(main_account=main_user_obj, to_merge=user_to_merge, preserve_authenticators=False)
            merged_count += 1
            self._log(f"  Successfully merged {service_type} user '{merge_orig_username}'", logging.INFO)

        self._log(f"  Migrating main user '{main_username}'", logging.INFO)
        migrate_account(main_user_obj)
        self._log(f"  Successfully migrated main user '{main_username}'", logging.INFO)
        merged_count += 1

        return merged_count

    @staticmethod
    def _format_fetched_assignment_for_logging(assignment_actor: AssignmentActorType, assignment: Dict[str, Any]) -> str:
        return (
            f"{assignment_actor.value}_id: {assignment.get(f'{assignment_actor.value}_ansible_id')}, "
            f"object_type: {assignment.get('content_type')}, "
            f"object_ansible_id: {assignment.get('object_ansible_id')}, "
            f"role_definition_name: {assignment.get('role_definition')}"
        )

    @staticmethod
    def _format_migrated_assignment_for_logging(role_assignment: RoleUserAssignment | RoleTeamAssignment) -> str:
        actor_msg = None
        if isinstance(role_assignment, RoleUserAssignment):
            actor_msg = f"username: {role_assignment.user.username}"
        elif isinstance(role_assignment, RoleTeamAssignment):
            actor_msg = f"team: {role_assignment.team.name}"
        return f"{actor_msg}, object_id: {role_assignment.object_id}, role_definition_name: {role_assignment.role_definition.name}"

    # Sentinel value for _resolve_content_object to signal "skip this assignment"
    _SKIP = object()

    def _resolve_role_definition(self, role_definition_name: str) -> Optional[RoleDefinition]:
        """Look up a RoleDefinition by name. Returns the object or None if not found."""
        try:
            return RoleDefinition.objects.get(name=role_definition_name)
        except RoleDefinition.DoesNotExist:
            self._log(f"Warning: Unable to find role definition {role_definition_name}, skipping assignment", logging.WARNING)
            return None

    def _resolve_gateway_actor(self, assignment_actor: AssignmentActorType, service_actor_ansible_id: str) -> Optional[Any]:
        """Look up the gateway actor (user or team) by ansible_id. Returns the content object or None if not found."""
        try:
            return Resource.objects.get(ansible_id=service_actor_ansible_id).content_object
        except Resource.DoesNotExist:
            self._log(
                f"Warning: Unable to find gateway {assignment_actor.value} with ansible_id {service_actor_ansible_id}, skipping assignment",
                logging.WARNING,
            )
            return None

    def _resolve_content_object(self, assignment: Dict[str, Any]) -> Any:
        """Resolve the content object for a role assignment.

        Returns the resolved content object (which may be None for global assignments),
        or ``Command._SKIP`` to signal that this assignment should be skipped.
        """
        service_content_object_ansible_id = assignment.get('object_ansible_id')
        service_content_object_id = assignment.get('object_id')
        content_type = assignment.get('content_type', '')

        try:
            if service_content_object_ansible_id:
                # Object is a gateway resource identified by ansible_id
                return Resource.objects.get(ansible_id=service_content_object_ansible_id).content_object
            elif service_content_object_id:
                # Object is remote (not a gateway resource); use RemoteObject with DABContentType
                service, model = content_type.split('.')
                ct = DABContentType.objects.get(service=service, model=model)
                return RemoteObject(ct, service_content_object_id)
            else:
                # No object reference means a global role assignment
                return None
        except Resource.DoesNotExist:
            self._log(
                f"Warning: Unable to find object of type {content_type} with ansible_id {service_content_object_ansible_id}, skipping assignment",
                logging.WARNING,
            )
            return Command._SKIP
        except ValueError:
            self._log(f"Warning: Malformed content_type '{content_type}', expected 'service.model' format, skipping assignment", logging.WARNING)
            return Command._SKIP
        except DABContentType.DoesNotExist:
            self._log(
                f"Warning: Unable to find content type '{content_type}' for remote object with id {service_content_object_id}, skipping assignment",
                logging.WARNING,
            )
            return Command._SKIP

    @staticmethod
    def _get_role_definitions_to_exclude(service_type: str) -> List[str]:
        # Since the goal is to honor controller's assignments platform roles, we do not want to consider
        # roles like 'Organization Admin' or 'Team Admin' from other services, just controller
        DEFAULT_EXCLUSION_SET = {'Platform Auditor', 'Organization Admin', 'Organization Member', 'Team Admin', 'Team Member'}
        ROLE_EXCLUSION_SETS = {
            # For controller, exclude nothing
            DefaultServiceType.CONTROLLER.value: {},
            # For hub, exclude platform roles but don't exclude 'Team Member'
            DefaultServiceType.HUB.value: DEFAULT_EXCLUSION_SET - {'Team Member'},
        }
        return sorted(ROLE_EXCLUSION_SETS.get(service_type, DEFAULT_EXCLUSION_SET))

    def _fetch_role_assignments(self, assignment_actor: AssignmentActorType, service_slug: str, service_type_name: str) -> Iterator[Dict[str, Any]]:
        """
        Fetch all role_assignments for team or user from the service with pagination
        """
        role_definitions_to_exclude = self._get_role_definitions_to_exclude(service_type_name)
        page = 1
        total_count = None  # we will check this on each page to see if anything changed
        while True:
            self._log(f"Fetching page {page} of role {assignment_actor.value} assignments from {service_slug}", logging.INFO)
            filters: Dict[str, int | str] = {'page': page, **self.BIG_PAGE_FILTERS}
            if role_definitions_to_exclude:
                filters['not__role_definition__name__in'] = ','.join(role_definitions_to_exclude)
            if assignment_actor == AssignmentActorType.USER:
                method = self.client.list_user_assignments
            elif assignment_actor == AssignmentActorType.TEAM:
                method = self.client.list_team_assignments
            else:
                raise RuntimeError(f"Invalid actor type {assignment_actor} to fetch")
            json_response = method(filters=filters).json()
            if total_count is None:
                total_count = json_response.get('count', 0)
                self._current_assignment_total = total_count
            elif total_count != json_response.get('count', 0):
                new_count = json_response.get('count', 0)
                self._log(
                    f"Role {assignment_actor.value} assignment count changed from {total_count} to {new_count}"
                    " during pagination (concurrent modification); continuing but will need re-run",
                    logging.WARNING,
                )
                total_count = new_count
                self._services_with_count_drift.add(service_slug)
            for assignment in json_response.get('results', []):
                yield assignment
            if not json_response.get('next'):
                break
            page += 1

    def migrate_role_assignments(self, assignment_actor: AssignmentActorType, service_slug: str, service_type_name: str) -> None:
        """
        Migrates the role_user_assignments from an individual service to platform-level role assignments

        This method must run after Organizations/Teams/Users have been migrated. It migrates the role assignments,
        so the subjects and objects of those assignments must exist.

        It performs this migration by:

        1. Querying the service's role assignments API specific to the actor type (team or user)
        2. Looking up the local (aap-gateway) actor referenced in each assignment
        3. Looking up the local (aap-gateway) role definition corresponding to the service definition
        4. Giving permission in gateway to the actor for the object (handling both Resources and RemoteObjects)
        """

        progress_label = f"{service_slug} {assignment_actor.value} role assignments"
        # Initialized here, updated by _fetch_role_assignments on the first page response
        self._current_assignment_total = 0
        self._log(f"Migrating {assignment_actor.value} role assignments from {service_slug} of type {service_type_name}", logging.INFO)
        try:
            assignments = self._fetch_role_assignments(assignment_actor, service_slug, service_type_name)
            processed = 0
            for assignment in assignments:
                processed += 1
                self._log_progress(progress_label, processed, self._current_assignment_total)
                log_detail = self._format_fetched_assignment_for_logging(assignment_actor, assignment)
                self._log(f"Processing assignment in service {service_slug}: {log_detail}", logging.INFO)

                role_definition_name = assignment.get('role_definition')
                service_actor_ansible_id = assignment.get(f'{assignment_actor.value}_ansible_id')

                try:
                    gateway_role_definition = self._resolve_role_definition(role_definition_name)
                    if gateway_role_definition is None:
                        continue

                    gateway_actor = self._resolve_gateway_actor(assignment_actor, service_actor_ansible_id)
                    if gateway_actor is None:
                        continue

                    gateway_content_object = self._resolve_content_object(assignment)
                    if gateway_content_object is Command._SKIP:
                        continue
                except Exception as e:
                    self._log(f"Error: Unable to process role {assignment_actor.value} assignment, skipping: {str(e)}", logging.WARNING)
                    continue

                try:
                    if gateway_content_object:
                        role_assignment = gateway_role_definition.give_permission(gateway_actor, gateway_content_object)
                    else:
                        role_assignment = gateway_role_definition.give_global_permission(gateway_actor)
                    self._log(f"Gave permission: {self._format_migrated_assignment_for_logging(role_assignment)}", logging.INFO)  # type: ignore
                except Exception as e:
                    self._log(f"Error: Unable to give permission for role {assignment_actor.value} assignment, skipping: {str(e)}", logging.WARNING)
                    continue
        except Exception as e:
            self._log(f"Unable to fetch role {assignment_actor.value} assignments from {service_slug}, skipping: {e}", logging.WARNING)
            return
