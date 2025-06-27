import logging
from typing import List, Optional

from ansible_base.resource_registry.models import service_id
from django.db import transaction
from django.utils.translation import gettext as _
from requests.exceptions import HTTPError
from rest_framework.exceptions import ValidationError as DRFValidationError

from aap_gateway_api.models import ServiceAPIRoute, User
from aap_gateway_api.utils.resources_client import GWResourceAPIClient, ResourceRequestBody

logger = logging.getLogger('aap_gateway_api.utils.user_migration')


def can_accounts_be_merged(main_account: User, to_merge: User) -> bool:
    """Check if two user accounts can be safely merged.

    Validates that the accounts are different and that the main account
    doesn't already have a migrated account from the same service as
    the account to be merged.

    Args:
        main_account: The primary user account to merge into
        to_merge: The secondary user account to be merged

    Returns:
        True if accounts can be merged

    Raises:
        DRFValidationError: If accounts cannot be merged due to conflicts
    """
    if main_account.pk == to_merge.pk:
        DRFValidationError(_("Can't merge an account with itself."))

    main_account_migrated_services = main_account.original_accounts.values_list("service", flat=True)
    for original_account in to_merge.original_accounts.all():
        if original_account.service.pk in main_account_migrated_services:
            raise DRFValidationError(
                _(
                    "Account %(username)s has already been linked to an account from "
                    "%(service_type)s. Only one migrated account from each service may be linked."
                )
                % {"service_type": original_account.service.service_type.name, "username": main_account.username}
            )

    return True


def migrate_account(user: User) -> None:
    """Migrate a user account to fully migrated status.

    Updates the user's resource registry entry to mark it as fully migrated
    and synchronizes the user data across all associated services.

    Args:
        user: The user account to migrate

    Note:
        This function is idempotent - calling it on an already migrated
        user will have no effect.
    """
    logger.debug(f"Migrating user {user.username} into Gateway.")
    if user.is_migrated:
        logger.debug(f"Migrating user {user.username} is already migrated")
        return

    with transaction.atomic():
        acct_resource = user.resource
        acct_resource.service_id = service_id()
        acct_resource.is_partially_migrated = False
        acct_resource.save()

        for original in user.original_accounts.all():
            service = ServiceAPIRoute.objects.get(service_cluster=original.service)
            client = GWResourceAPIClient(service=service, raise_if_bad_request=True)

            body = ResourceRequestBody(
                service_id=acct_resource.service_id,
                resource_data={
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                },
                is_partially_migrated=False,
            )

            client.update_resource(acct_resource.ansible_id, data=body, partial=True)


def link_account(
    main_account: User,
    to_merge: User,
    preserve_authenticators: bool = True,
    services_to_merge: Optional[List[ServiceAPIRoute]] = None,
) -> None:
    """Link and merge two user accounts.

    Merges the secondary account into the main account, transferring all
    associated metadata, authenticators, and service references. The
    secondary account is deleted after successful merge.

    Args:
        main_account: The primary user account to merge into
        to_merge: The secondary user account to be merged and deleted
        preserve_authenticators: Whether to transfer authenticator relationships
        services_to_merge: Optional list of specific services to merge,
            defaults to all services associated with to_merge account

    Note:
        This operation is performed within a database transaction to ensure
        data consistency. If any part fails, all changes are rolled back.
    """
    logger.debug(f"Merging account {to_merge.username} into account {main_account.username}")

    if main_account.pk == to_merge.pk:
        return
    with transaction.atomic():
        original_services = []
        if services_to_merge:
            original_services = services_to_merge
        for original in to_merge.original_accounts.all():
            original_services.append(ServiceAPIRoute.objects.get(service_cluster=original.service))
            original.user = main_account
            original.save()

        if preserve_authenticators:
            for auth_user in to_merge.authenticator_users.all():
                auth_user.user = main_account
                auth_user.save()

        to_merge_id = to_merge.resource.ansible_id
        to_merge.delete()

        for service in original_services:
            client = GWResourceAPIClient(service=service, raise_if_bad_request=True)

            # clean up any references to the original account if they got created.
            try:
                logger.debug(f"Removing {main_account.username} account from {client.service.service_cluster.name}")
                client.delete_resource(ansible_id=main_account.resource.ansible_id)
            except HTTPError as e:
                if e.response.status_code != 404:
                    raise

            logger.debug(f"Updating account {to_merge_id} to point to {main_account.username}")
            client.update_resource(
                to_merge_id,
                data=ResourceRequestBody(
                    ansible_id=main_account.resource.ansible_id,
                    service_id=service_id(),
                    is_partially_migrated=False,
                    resource_data={"username": main_account.username},
                ),
                partial=True,
            )
            logger.debug(f"Accounts {to_merge.username} and {main_account.username} merged successfully")
