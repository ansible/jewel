import logging
from typing import Dict, List, Optional

from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE
from ansible_base.resource_registry.models import service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.management.base import CommandError

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils import resources_client

User = get_user_model()


class SuperuserSyncMixin:
    def _get_gateway_user(self, username: str) -> Optional[AbstractUser]:
        """Get Gateway user by username, returning None if not found."""
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            return None

    def _sync_controller_superuser(self, upstream_resource: Dict[str, any], username: str, upstream_is_superuser: bool) -> None:
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

    def _sync_hub_eda_superuser(self, upstream_resource: Dict[str, any], username: str, upstream_is_superuser: bool, service_type: str) -> None:
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

    def _sync_user_superuser_flag(self, upstream_resource: Dict[str, any], validated_resource_data: Dict[str, any]) -> Dict[str, any]:
        """
        Sync superuser flags between services according to the following requirements.

        Controller -> Gateway: If Controller user is superuser, promote Gateway user to superuser
        Gateway -> Hub/EDA: Sync Gateway superuser status to upstream service

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

        # Validate Controller <-> Gateway consistency
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
