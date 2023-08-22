from aap_gateway_api.models import Service
from aap_gateway_api.serializers import NamedCommonModelSerializer


class ServiceSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'service-detail'

    class Meta:
        model = Service
        fields = NamedCommonModelSerializer.Meta.fields + ('url_to_proxy_to', 'service_type', 'ignore_ssl', 'environment')
