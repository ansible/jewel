from django.utils.translation import gettext as _
from rest_framework import serializers

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.serializers.base_route import BaseRouteSerializer


class ServiceAPIRouteSerializer(BaseRouteSerializer):
    class Meta:
        model = ServiceAPIRoute
        fields = BaseRouteSerializer.Meta.fields + [
            'http_port',
            'service_cluster',
            'service_port',
            'is_service_https',
            'is_internal_route',
            'is_container_registry',
            'service_path',
            'gateway_path',
            'description',
            'api_slug',
            'enable_gateway_auth',
            'order',
            'node_tags',
            'enable_mtls',
        ]

        read_only_fields = ('gateway_path',)

    def validate_http_port(self, value):
        """
        A given http_port must be an API port.
        """
        if not (value and value.is_api_port):
            raise serializers.ValidationError(_("An API HTTP port must be used with API routes"))
        return value
