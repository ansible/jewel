import logging

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.models.authenticator import Authenticator


class LegacyAuthenticatorsMixin:
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
