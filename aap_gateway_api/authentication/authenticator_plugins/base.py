import logging

import requests
from django.db import transaction

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.resources_client import GWResourceAPIClient
from aap_gateway_api.utils.user_migration import link_account, migrate_account

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.base')

_API_SLUGS = ["awx", "controller", "eda", "galaxy"]


class LegacyMixin:
    """
    Mixin for supporting legacy authentication from controller and hub services (pre-2.5)
    """

    def move_authenticator_user_to(self, new_user, old_authenticator_user):
        """
        Merges the old authenticator user into the new user account in gateway
        This includes migrating the new user account if necessary, linking accounts
        across services, and cleaning up old user locally in gateway and in the services as well
        Returns: None when new user is already or successfully linked
        """

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
                # As link_account will delete the old user locally we need to preserve its
                # ansible id and username for our later use.
                old_user_ansible_id = old_user.resource.ansible_id
                old_user_username = old_user.username

                # This has to come last since it needs to delete the local old user.
                link_account(new_user, old_user, preserve_authenticators=False, services_to_merge=services)

                # Having performed the link we want to remove the old user from any remote
                # service on which it remains.
                for slug in _API_SLUGS:
                    # We need a client connection to the service.
                    try:
                        service_api = ServiceAPIRoute.objects.get(api_slug=slug)
                    except ServiceAPIRoute.DoesNotExist:
                        # Not all services are necessarily extant in the environment.
                        # Log the occurrence at debug level as for this current
                        # implementation it's not unexpected.
                        logger.debug(f"Service with API slug {slug} does not exist.")
                        continue

                    client = GWResourceAPIClient(service_api, raise_if_bad_request=True)
                    logger.debug(f"Removing moved {old_user_username} account from service with API slug {slug}.")
                    try:
                        client.delete_resource(ansible_id=old_user_ansible_id)
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code != requests.codes.not_found:
                            raise
            else:
                logger.debug(f"User {new_user.username} is already set up with this authenticator.")

        return None

    def authenticate(self, request, username=None, password=None, service_type=None, **kwargs):
        """
        This method by default returns None to prevent breakage of AnsibleBaseAuth
        Overrides may use 'request', 'username', 'password', 'service_type', or 'kwargs'
        to implement custom authentication logic based on request context, user credentials,
        service-specific behavior, or additional data passed in.
        """
        return None
