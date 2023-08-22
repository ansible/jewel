from aap_gateway_api.models import Environment
from aap_gateway_api.serializers import NamedCommonModelSerializer


class EnvironmentSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'environment-detail'

    class Meta:
        model = Environment
        fields = NamedCommonModelSerializer.Meta.fields
