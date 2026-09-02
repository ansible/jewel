from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import CleanTextMixin

from aap_gateway_api.models import Organization


class OrganizationSerializer(CleanTextMixin, NamedCommonModelSerializer):
    class Meta:
        model = Organization
        fields = NamedCommonModelSerializer.Meta.fields + [
            'description',
            'managed',
        ]
