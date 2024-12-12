import logging

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.models import AuthenticatorUser
from django.core.exceptions import ValidationError

from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.utils.resources_client import AllServicesClient
from aap_gateway_api.utils.service_token import validate_service_token

logger = logging.getLogger('aap_gateway_api.authentication.authenticator_plugins.legacy_external_password')


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    configuration_class = BaseAuthenticatorConfiguration
    logger = logger
    type = "legacy_external_password"
    category = "legacy"

    def authenticate(self, request, username=None, password=None, service_type=None, **kwargs):
        if not self.database_instance:
            return

        try:
            user = AuthenticatorUser.objects.get(uid=username, provider=self.database_instance).user
        except AuthenticatorUser.DoesNotExist:
            return

        user_services = user.original_accounts.exclude(
            service__service_type__name=DefaultServiceType.EDA.value,
        ).values_list("service", flat=True)

        client = AllServicesClient(wait_for_response=True, service_filter={"service_cluster__pk__in": user_services})

        responses = client.validate_local_user(user.username, password)

        if len(responses) == 0:
            return

        for resp in responses.values():

            if resp.status_code != 200:
                return
            try:
                token = validate_service_token(resp.json()["auth_code"], required_type="auth_code")
                if token["user"].pk != user.pk:
                    return
            except ValidationError:
                return

        return user
