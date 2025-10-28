from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from rest_framework import serializers

from aap_gateway_api.models import DefaultServiceType, ServiceCluster, UIPluginRoute
from aap_gateway_api.utils.formatting import normalize_comma_separated_list


class UIPluginRouteSerializer(NamedCommonModelSerializer):
    class Meta:
        model = UIPluginRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'http_port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'gateway_path',
            'description',
            'ui_plugin_path',
            'order',
            'node_tags',
        ]

        read_only_fields = ('gateway_path', 'service_path', 'enable_gateway_auth', 'is_internal_route')

    service_cluster = serializers.PrimaryKeyRelatedField(queryset=ServiceCluster.objects.exclude(service_type__name=DefaultServiceType.GATEWAY))

    def validate_node_tags(self, value):
        return normalize_comma_separated_list(value)

    def validate_ui_plugin_path(self, value):
        return value.strip('/')
