import logging

from django.db import transaction

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.user_migration import link_account, migrate_account

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.base')


class LegacyMixin:
    def move_authenticator_user_to(self, new_user, old_authenticator_user):
        with transaction.atomic():
            logger.debug(f'Merging {old_authenticator_user.uid} from {old_authenticator_user.provider.name} into {new_user.username}')
            # Ensure that the new account has been migrated if it hasn't.
            migrate_account(new_user)

            # This has to come before the call to super(). We need to get the list of services the user came
            # from before calling super().move_authenticator_user_to because that call will clean up the old
            # authenticator user and thus remove the original_accounts
            services = [ServiceAPIRoute.objects.get(service_cluster=u.service) for u in old_authenticator_user.user.original_accounts.all()]

            # Call super to make sure that the user's related fields are copied to the new user
            old_user = super().move_authenticator_user_to(new_user, old_authenticator_user)

            # If the old user is already linked with this account, don't try to re-link it.
            if old_user is not None:

                # This has to come last since it needs to delete the old user.
                link_account(new_user, old_user, preserve_authenticators=False, services_to_merge=services)

            else:
                logger.debug(f"User {new_user.username} is already set up with this authenticator.")

        return None
