from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from aap_gateway_api.models import AdditionalRoute
from aap_gateway_api.models.additional_route import get_gateway_path_prefix_error_message
from aap_gateway_api.models.route import API_PREFIX
from aap_gateway_api.models.ui_plugin_route import PLUGIN_PREFIX
from aap_gateway_api.serializers.base_route import BaseRouteSerializer


class AdditionalRouteSerializer(BaseRouteSerializer):
    reverse_url_name = 'route-detail'

    class Meta:
        model = AdditionalRoute
        fields = BaseRouteSerializer.Meta.fields + [
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
            'enable_mtls',
        ]

    def validate(self, attrs):
        """
        Perform validation for additional routes.

        First performs base validation, then validates that additional routes
        on API ports don't use reserved path prefixes (API_PREFIX or PLUGIN_PREFIX).

        Args:
            attrs: Dictionary of attributes to validate

        Returns:
            Validated attributes dictionary

        Raises:
            ValidationError: If validation fails
        """
        # Perform base validation first (includes mTLS validation)
        attrs = super().validate(attrs)

        errors = {}

        # Validate that additional routes on API ports don't use reserved prefixes
        if (
            attrs.get("http_port")
            and attrs["http_port"].is_api_port
            and attrs.get("gateway_path")
            and (attrs["gateway_path"].startswith(API_PREFIX) or attrs["gateway_path"].startswith(PLUGIN_PREFIX))
        ):
            errors.setdefault('gateway_path', []).append(
                ErrorDetail(
                    get_gateway_path_prefix_error_message(),
                    code='required',
                )
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
