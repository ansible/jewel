from rest_framework import serializers

from aap_gateway_api.models import DomainDefinition


class DomainDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainDefinition
        fields = ('scope', 'domains')
        read_only_fields = ('scope',)

    def validate_domains(self, value):
        return self.validate_domain_list(value)

    @staticmethod
    def validate_domain_list(value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Domains must be a list.')
        for domain in value:
            if not isinstance(domain, dict) or not isinstance(domain.get('name'), str) or not domain['name']:
                raise serializers.ValidationError('Each domain must have a non-empty name.')
            if {'scope', 'scopeId', 'scopeName'} & domain.keys():
                raise serializers.ValidationError('Domain scope metadata is read-only.')
            if not isinstance(domain.get('labels', []), list):
                raise serializers.ValidationError('Domain labels must be a list.')
            for label in domain.get('labels', []):
                if not isinstance(label, dict) or not isinstance(label.get('name'), str) or not label['name']:
                    raise serializers.ValidationError('Each domain label must have a non-empty name.')
        return value
