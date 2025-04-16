from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.models.route import API_PREFIX


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

    def validate_is_api_port(self, value):
        """
        Prevent changing is_api_port from True to False, which would cause the
        proxy to become inoperable. This is normally prevented by DisallowWriteFromProxy
        but is added here as another layer of protection in case someone manages to directly
        access Gateway.
        """
        if self.instance and self.instance.is_api_port and not value:
            raise serializers.ValidationError(_("The API port cannot be changed to a non-API port"))
        return value


class ServiceClusterSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceCluster
        fields = NamedCommonModelSerializer.Meta.fields + [
            'service_type',
            'service_id',
            'auth_type',
            'upstream_hostname',
            'dns_discovery_type',
            'dns_lookup_family',
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
            'healthy_panic_threshold',
        ]


class ServiceTypeSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceType
        fields = NamedCommonModelSerializer.Meta.fields + [
            'login_path',
            'logout_path',
            'ping_url',
            'service_index_path',
        ]


def _validate_gateway_auth_if_internal_route(enable_gateway_auth, is_internal_route, errors):
    if not enable_gateway_auth and is_internal_route:
        errors.setdefault('is_internal_route', []).append(ErrorDetail(_("Internal routes require gateway auth to be enabled"), code='required'))


class ServiceAPIRouteSerializer(NamedCommonModelSerializer):
    class Meta:
        model = ServiceAPIRoute
        fields = NamedCommonModelSerializer.Meta.fields + [
            'http_port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'is_internal_route',
            'service_path',
            'gateway_path',
            'description',
            'api_slug',
            'enable_gateway_auth',
            'order',
            'node_tags',
        ]

        read_only_fields = ('gateway_path',)

    def validate(self, data):
        """
        Perform cross-field validation for enable_gateway_auth and is_internal_route flags,
        is_internal_route cannot be set without gateway auth enabled.

        Raises ValidationError if any validation fails.
        """
        enable_gateway_auth = data.get('enable_gateway_auth')
        is_internal_route = data.get('is_internal_route')

        errors = {}

        _validate_gateway_auth_if_internal_route(enable_gateway_auth, is_internal_route, errors)

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def validate_node_tags(self, value):
        return _validate_tags_field(value)

    def validate_http_port(self, value):
        """
        A given http_port must be an API port.
        """
        if not (value and value.is_api_port):
            raise serializers.ValidationError(_("An API HTTP port must be used with API routes"))
        return value


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
            'is_internal_route',
            'service_path',
            'gateway_path',
            'description',
            'enable_gateway_auth',
            'node_tags',
        ]

    def validate_node_tags(self, value):
        return _validate_tags_field(value)

    def validate(self, attrs):
        enable_gateway_auth = attrs.get('enable_gateway_auth')
        is_internal_route = attrs.get('is_internal_route')

        errors = {}

        _validate_gateway_auth_if_internal_route(enable_gateway_auth, is_internal_route, errors)

        if attrs.get("http_port") and attrs["http_port"].is_api_port and attrs.get("gateway_path") and attrs["gateway_path"].startswith(API_PREFIX):
            errors.setdefault('gateway_path', []).append(
                ErrorDetail(_("Custom routes on the API port cannot start with '{API_PREFIX}'".format(API_PREFIX=API_PREFIX)), code='required')
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
