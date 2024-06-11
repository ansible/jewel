from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import Organization


class OrganizationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = Organization
        fields = NamedCommonModelSerializer.Meta.fields + [
            'description',
            'managed',
        ]
