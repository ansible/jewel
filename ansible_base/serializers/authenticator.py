from collections import OrderedDict

from rest_framework.serializers import ValidationError

from ansible_base.authentication.ldap.backends import LDAPSettings
from ansible_base.models import Authenticator
from ansible_base.utils.encryption import ENCRYPTED_STRING

from .common import NamedCommonModelSerializer


class AuthenticatorSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'authenticator-detail'

    class Meta:
        model = Authenticator
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in Authenticator._meta.concrete_fields]

    # TODO: Do we need/want to delve into dicts and search their keys?
    def to_representation(self, authenticator):
        ret = super().to_representation(authenticator)
        configuration = authenticator.configuration
        masked_configuration = OrderedDict()
        keys = list(configuration.keys())
        encrypted_keys = []
        if authenticator.type == 'ldap':
            from ansible_base.authentication.ldap import configuration_encrypted_fields as encrypted_keys

        keys.sort()
        # Mask any keys in the encryption that should be masked
        for key in keys:
            if key in encrypted_keys:
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
        from ansible_base.authentication.ldap import configuration_encrypted_fields

        # If there are any encrypted keys we don't want to use ENCRYPTED_STRING if they were not updated
        for key in configuration_encrypted_fields:
            if key in data and data[key] == ENCRYPTED_STRING:
                data[key] = self.instance.configuration.get(key, None)

        settings = LDAPSettings(defaults=data)

        if settings.errors:
            raise ValidationError({"configuration": settings.errors})

        # Raise some warnings if specific fields were used
        # TODO: Figure out how to display these warnings on a successful save
        for field in ['USER_FLAGS_BY_GROUP', 'DENY_GROUP', 'REQUIRE_GROUP']:
            if field in data:
                self.warnings[field] = "It would be better to use the authenticator field instead of setting this field in the LDAP adapter"
