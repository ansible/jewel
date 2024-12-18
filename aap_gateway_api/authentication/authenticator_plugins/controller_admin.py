import logging

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from django.core.exceptions import ValidationError
from django.db import transaction

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.resources_client import GWResourceAPIClient
from aap_gateway_api.utils.service_token import classify_backend, validate_service_token

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.controller_admin')


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    configuration_class = BaseAuthenticatorConfiguration
    logger = logger
    type = "controller_admin"
    category = "password"

    def authenticate(self, request, username=None, password=None, service_type=None, **kwargs):
        try:
            service = ServiceAPIRoute.objects.get(service_cluster__service_type__name="controller")
        except ServiceAPIRoute.DoesNotExist:
            logger.error("Controller is not configured on this gateway instance.")
            return

        client = GWResourceAPIClient(
            service=service,
            raise_if_bad_request=False,
        )

        # Phish the user's controller password by sending the provided credentials to controller
        # and seeing if they are valid.
        response = client.validate_local_user(username=username, password=password)
        if response.status_code != 200:
            logger.error("Invalid username or password.")
            return
        try:
            validated_auth_code = validate_service_token(response.json()["auth_code"], required_type="auth_code")
        except ValidationError:
            logger.error("The auth code returned by controller is invalid.")
            return

        # Check that controller authenticated the user with the django user table. We don't want to
        # steal passwords out of something like LDAP.
        if classify_backend(validated_auth_code["token_data"]["payload"].get("auth_backend")) != "local":
            logger.error(f"{username} must have a local password in controller.")
            return

        user = validated_auth_code["user"]

        with transaction.atomic():
            # Set the phished password on the gateway account
            user.set_password(password)
            user.save()

            # Self destruct the AuthenticatorUser for this account as well as the instance of this
            # authenticator if no more users are present.
            user.authenticator_users.filter(provider=self.database_instance).delete()
            if self.database_instance.authenticator_providers.count() == 0:
                self.database_instance.delete()

        return user
