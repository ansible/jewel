from rest_framework import serializers

from aap_gateway_api.models import UserPreference
from aap_gateway_api.serializers.domain_definition import DomainDefinitionSerializer


class UserPreferenceSerializer(serializers.ModelSerializer):
    def validate_value(self, value):
        if self.context.get('preference_name') != 'domains':
            return value

        if not isinstance(value, dict):
            raise serializers.ValidationError('Domain preferences must be an object.')

        missing_fields = {'domains', 'activeDomains'} - value.keys()
        if missing_fields:
            raise serializers.ValidationError({field: 'This field is required.' for field in sorted(missing_fields)})

        for field in ('domains', 'activeDomains'):
            if not isinstance(value[field], list):
                raise serializers.ValidationError({field: 'Expected a list of domains.'})
            try:
                DomainDefinitionSerializer.validate_domain_list(value[field])
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({field: exc.detail}) from exc

        return value

    class Meta:
        model = UserPreference
        fields = ('name', 'value')
        read_only_fields = ('name',)
