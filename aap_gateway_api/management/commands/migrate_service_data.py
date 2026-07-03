import logging
from collections import OrderedDict
from typing import Dict, List, Tuple

from ansible_base.lib.utils.settings import get_setting
from ansible_base.resource_registry.constants import (
    SHARED_AAP_FLAG_RESOURCE_TYPE,
    SHARED_ORGANIZATION_RESOURCE_TYPE,
    SHARED_ROLE_DEFINITION_RESOURCE_TYPE,
    SHARED_TEAM_RESOURCE_TYPE,
    SHARED_USER_RESOURCE_TYPE,
)
from ansible_base.resource_registry.models import ResourceType
from ansible_base.rest_pagination.default_paginator import DEFAULT_MAX_PAGE_SIZE
from django.contrib.auth.models import AbstractUser
from django.core.management.base import BaseCommand, CommandError

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore as _CursorStore  # noqa: F401 — re-export for test compat
from aap_gateway_api.management.commands._migrate_service_data.legacy_authenticators import LegacyAuthenticatorsMixin
from aap_gateway_api.management.commands._migrate_service_data.logging_mixin import PROGRESS_STEP, LoggingMixin
from aap_gateway_api.management.commands._migrate_service_data.resource_migration import ResourceMigrationMixin
from aap_gateway_api.management.commands._migrate_service_data.role_assignments import RoleAssignmentsMixin
from aap_gateway_api.management.commands._migrate_service_data.service_orchestration import ServiceOrchestrationMixin
from aap_gateway_api.management.commands._migrate_service_data.superuser_sync import SuperuserSyncMixin
from aap_gateway_api.management.commands._migrate_service_data.user_merge import UserMergeMixin
from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan
from aap_gateway_api.models.service_type import DefaultServiceType

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')


class Command(
    LoggingMixin,
    LegacyAuthenticatorsMixin,
    ResourceMigrationMixin,
    RoleAssignmentsMixin,
    ServiceOrchestrationMixin,
    SuperuserSyncMixin,
    UserMergeMixin,
    BaseCommand,
):
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
    PROGRESS_STEP = PROGRESS_STEP

    # Service processing order - Controller first to establish priority for user merging
    SERVICE_TYPE_ORDER = [
        DefaultServiceType.CONTROLLER.value,
        DefaultServiceType.HUB.value,
        DefaultServiceType.EDA.value,
        DefaultServiceType.METRICS.value,
    ]

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

        # Get all services with DefaultServiceType in exact order: controller, hub, eda and metrics
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

        if failed_services:
            self._log("\nFailed to migrate the following services:", logging.WARNING)
            for service_slug, error in failed_services.items():
                self._log(f"  - {service_slug}: {error}", logging.WARNING)
            raise CommandError(f"Migration failed for {len(failed_services)} service(s): {', '.join(failed_services)}. See error details above.")

        self._ensure_superuser_consistency(service_apis, user)

        self._log("\n=== Re-enabling service authentication ===", logging.INFO)
        MigrateServiceDataHasRan.mark_migration_completed()
        self._log("✓ Migration flag updated: Service authentication is now enabled.", logging.INFO)
        self._log("\nAll services migration completed successfully!", logging.INFO)
