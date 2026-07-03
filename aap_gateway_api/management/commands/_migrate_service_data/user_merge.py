import logging
from typing import Dict, List, Tuple

from ansible_base.resource_registry.constants import SHARED_USER_RESOURCE_TYPE
from ansible_base.resource_registry.models import Resource, service_id
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.user_migration import can_accounts_be_merged, link_account, migrate_account

User = get_user_model()


class UserMergeMixin:
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
