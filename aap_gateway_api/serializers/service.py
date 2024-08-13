from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from django.utils.translation import gettext as _
from rest_framework import serializers

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode
from aap_gateway_api.models.service import API_PREFIX


def _validate_tags_field(value):
    if not value:
        return value
    cleaned_tags = set()
    for tag in value.split(','):
        tag = tag.strip()
        if not tag:
            continue
        cleaned_tags.add(tag)
    return ','.join(cleaned_tags)


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
            'outlier_detection_enabled',
            'outlier_detection_consecutive_5xx',
            'outlier_detection_interval_seconds',
            'outlier_detection_base_ejection_time_seconds',
            'outlier_detection_max_ejection_percent',
            'health_checks_enabled',
            'health_check_timeout_seconds',
            'health_check_interval_seconds',
            'health_check_unhealthy_threshold',
            'health_check_healthy_threshold',
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
            'node_tags',
        ]

        read_only_fields = ('gateway_path',)

    def validate_node_tags(self, value):
        return _validate_tags_field(value)


class ServiceNodeSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceNode
        fields = NamedCommonModelSerializer.Meta.fields + ['address', 'service_cluster', 'tags']

    def validate_tags(self, value):
        return _validate_tags_field(value)


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
            'node_tags',
        ]

    def validate_node_tags(self, value):
        return _validate_tags_field(value)

    def validate(self, attrs):
        if attrs.get("http_port") and attrs["http_port"].is_api_port and attrs.get("gateway_path") and attrs["gateway_path"].startswith(API_PREFIX):
            raise serializers.ValidationError(
                {'gateway_path': _("Custom routes on the API port cannot start with '{API_PREFIX}'".format(API_PREFIX=API_PREFIX))}
            )

        return attrs
