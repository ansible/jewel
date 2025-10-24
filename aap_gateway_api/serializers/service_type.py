from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import ServiceType


class ServiceTypeSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceType
        fields = NamedCommonModelSerializer.Meta.fields + [
            'login_path',
            'logout_path',
            'ping_url',
            'service_index_path',
        ]
