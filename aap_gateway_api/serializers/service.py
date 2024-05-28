from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from django.utils.translation import gettext as _
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
            'service_id',
        ]


class ServiceAPIRouteSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceAPIRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'http_port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'service_path',
            'gateway_path',
            'description',
            'api_slug',
            'enable_gateway_auth',
            'order',
        ]

        read_only_fields = ('gateway_path',)


class ServiceNodeSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceNode
        fields = NamedCommonModelSerializer.Meta.fields + ['address', 'service_cluster']


class AdditionalRouteSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'route-detail'

    class Meta:
        model = AdditionalRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'http_port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'service_path',
            'gateway_path',
            'description',
            'enable_gateway_auth',
        ]

    def validate(self, attrs):
        if attrs.get("http_port") and attrs["http_port"].is_api_port and attrs.get("gateway_path") and attrs["gateway_path"].startswith(API_PREFIX):
            raise serializers.ValidationError(
                {'gateway_path': _("Custom routes on the API port cannot start with '{API_PREFIX}'".format(API_PREFIX=API_PREFIX))}
            )

        return attrs
