from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.user_migration import link_account, migrate_account


class LegacyMixin:
    def move_authenticator_user_to(self, new_user, old_authenticator_user):
        # Ensure that the new account has been migrated if it hasn't.
        migrate_account(new_user)

        services = [ServiceAPIRoute.objects.get(service_cluster=u.service) for u in old_authenticator_user.user.original_accounts.all()]

        # Call super to make sure that the user's related fields are copied to the new user
        old_user = super().move_authenticator_user_to(new_user, old_authenticator_user)

        # This has to come last since it needs to delete the old user.
        link_account(new_user, old_user, preserve_authenticators=False, services_to_merge=services)

        return None
