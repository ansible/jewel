from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import Environment


class EnvironmentSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'environment-detail'

    class Meta:
        model = Environment
        fields = NamedCommonModelSerializer.Meta.fields
