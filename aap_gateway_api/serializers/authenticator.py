from collections import OrderedDict

from rest_framework.serializers import ValidationError

from aap_gateway_api.authentication.ldap.backends import LDAPSettings
from aap_gateway_api.models import Authenticator
from aap_gateway_api.serializers.common import NamedCommonModelSerializer
from aap_gateway_api.utils import ENCRYPTED_STRING


class AuthenticatorSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'authenticator-detail'

    class Meta:
        model = Authenticator
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in Authenticator._meta.concrete_fields]

    # TODO: Ensure that encrypted strings are masked.... do we need/want to delve into dicts and search their keys?
    def to_representation(self, authenticator):
        ret = super().to_representation(authenticator)
        configuration = authenticator.configuration
        masked_configuration = OrderedDict()
        keys = list(configuration.keys())
        keys.sort()
        for key in keys:
            if type(configuration[key]) is str and configuration[key].startswith(ENCRYPTED_STRING):
                masked_configuration[key] = ENCRYPTED_STRING
            else:
                masked_configuration[key] = configuration[key]
        ret['configuration'] = masked_configuration
        return ret

    def validate(self, data) -> dict:
        validator_type = data.get('type', None)
        # if we didn't have a type, try to get the type of the existing object (if we have one)
        if not validator_type and self.instance:
            validator_type = self.instance.type

        if validator_type == 'l':
            self.validate_ldap_configuration(data['configuration'])
        else:
            # If its an invalid type it will already be caught but we could have a valid value that is not yet validated
            raise ValidationError(f"The specified type {type} has no validation yet")
        return data

    def validate_ldap_configuration(self, data: dict) -> None:
        settings = LDAPSettings(defaults=data)

        if settings.errors:
            raise ValidationError({"configuration": settings.errors})

        # Raise some warnings if specific fields were used
        # TODO: Figure out how to display these warnings on a successful save
        for field in ['USER_FLAGS_BY_GROUP', 'DENY_GROUP', 'REQUIRE_GROUP']:
            if field in data:
                self.warnings[field] = "It would be better to use the authenticator field instead of setting this field in the LDAP adapter"
