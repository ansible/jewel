from ansible_base.lib.serializers.common import CommonModelSerializer, NamedCommonModelSerializer
from rest_framework import serializers

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode
from aap_gateway_api.models.service import API_PREFIX


class HTTPPortSerializer(CommonModelSerializer):
    reverse_url_name = 'http_port-detail'

    class Meta:
        model = HTTPPort
        fields = CommonModelSerializer.Meta.fields + ['number', 'use_https', 'is_api_port']


class ServiceClusterSerializer(CommonModelSerializer):
    reverse_url_name = 'service_cluster-detail'

    class Meta:
        model = ServiceCluster
        fields = CommonModelSerializer.Meta.fields + [
            'service_type',
        ]


class ServiceAPIRouteSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'service-detail'

    class Meta:
        model = ServiceAPIRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'service_path',
            'gateway_path',
            'description',
            'api_slug',
            'order',
        ]

        read_only_fields = ('gateway_path',)


class ServiceNodeSerializer(CommonModelSerializer):
    reverse_url_name = 'service_node-detail'

    class Meta:
        model = ServiceNode
        fields = CommonModelSerializer.Meta.fields + ['address', 'service']


class AdditionalRouteSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'route-detail'

    class Meta:
        model = AdditionalRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'service_path',
            'gateway_path',
            'description',
        ]

    def validate(self, attrs):
        if attrs["port"].is_api_port and attrs["gateway_path"].startswith(API_PREFIX):
            raise serializers.ValidationError({'gateway_path': f"Custom routes on the API port cannot start with '{API_PREFIX}'"})

        return attrs
