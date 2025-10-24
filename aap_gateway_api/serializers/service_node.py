from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import ServiceNode
from aap_gateway_api.utils.formatting import normalize_comma_separated_list


class ServiceNodeSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceNode
        fields = NamedCommonModelSerializer.Meta.fields + ['address', 'service_cluster', 'tags']

    def validate_tags(self, value):
        return normalize_comma_separated_list(value)
