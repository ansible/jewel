from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from rest_framework import serializers

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode
from aap_gateway_api.models.service import API_PREFIX


class HTTPPortSerializer(NamedCommonModelSerializer):

    class Meta:
        model = HTTPPort
        fields = NamedCommonModelSerializer.Meta.fields + ['number', 'use_https', 'is_api_port']


class ServiceClusterSerializer(NamedCommonModelSerializer):

    class Meta:
        model = ServiceCluster
        fields = NamedCommonModelSerializer.Meta.fields + [
            'service_type',
        ]


class ServiceAPIRouteSerializer(NamedCommonModelSerializer):

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


class ServiceNodeSerializer(NamedCommonModelSerializer):

    class Meta:
        model = ServiceNode
        fields = NamedCommonModelSerializer.Meta.fields + ['address', 'service']


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
        if attrs.get("port") and attrs["port"].is_api_port and attrs.get("gateway_path") and attrs["gateway_path"].startswith(API_PREFIX):
            raise serializers.ValidationError({'gateway_path': f"Custom routes on the API port cannot start with '{API_PREFIX}'"})

        return attrs
