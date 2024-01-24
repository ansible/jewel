from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import Organization


class OrganizationSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'organization-detail'

    class Meta:
        model = Organization
        fields = NamedCommonModelSerializer.Meta.fields + [
            'environment',
        ]
