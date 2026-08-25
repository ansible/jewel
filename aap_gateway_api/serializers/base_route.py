from typing import Dict, List, Optional

from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import CleanTextMixin
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from aap_gateway_api.utils.formatting import normalize_comma_separated_list
from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.utils.urls import remove_multiple_slashes_from_path


class BaseRouteSerializer(CleanTextMixin, NamedCommonModelSerializer):
    """
    Base serializer for route models.

    Provides common validation logic for routes including:
    - Gateway authentication validation for internal routes
    - Mutual TLS (mTLS) validation with gateway authentication
    - Gateway path normalization (collapsing consecutive slashes)
    - Node tags normalization
    - Timeout floor enforcement (request_timeout_seconds & idle_timeout_seconds)

    Subclasses can override validate() and call super().validate()
    to add their own validation logic.
    """

    class Meta(NamedCommonModelSerializer.Meta):
        fields = NamedCommonModelSerializer.Meta.fields + [
            'request_timeout_seconds',
            'idle_timeout_seconds',
            'effective_timeout_seconds',
            'effective_idle_timeout_seconds',
        ]

    effective_timeout_seconds = serializers.SerializerMethodField(
        help_text=_("Read-only. The effective request timeout: max(request_timeout_seconds, global request_timeout setting).")
    )
    effective_idle_timeout_seconds = serializers.SerializerMethodField(
        help_text=_("Read-only. The effective idle timeout: max(idle_timeout_seconds, global idle_timeout setting).")
    )

    def get_effective_timeout_seconds(self, obj):
        return obj.get_effective_timeout_seconds()

    def get_effective_idle_timeout_seconds(self, obj):
        return obj.get_effective_idle_timeout_seconds()

    def validate_node_tags(self, value):
        """Normalize comma-separated node tags."""
        return normalize_comma_separated_list(value)

    def _validate_gateway_auth_if_internal_route(
        self, enable_gateway_auth: Optional[bool], is_internal_route: Optional[bool], errors: Dict[str, List[ErrorDetail]]
    ) -> None:
        """
        Validate that internal routes have gateway auth enabled.

        Internal routes require gateway authentication to be enabled for security.

        Args:
            enable_gateway_auth: Boolean indicating if gateway auth is enabled, or None
            is_internal_route: Boolean indicating if this is an internal route, or None
            errors: Dictionary to accumulate validation errors

        Returns:
            None (modifies errors dict in place)
        """
        if not enable_gateway_auth and is_internal_route:
            errors.setdefault('is_internal_route', []).append(ErrorDetail(_("Internal routes require gateway auth to be enabled"), code='required'))

    def _validate_gateway_auth_if_mtls_enabled(
        self, enable_gateway_auth: Optional[bool], enable_mtls: Optional[bool], errors: Dict[str, List[ErrorDetail]]
    ) -> None:
        """
        Validate that mTLS is only enabled when gateway auth is disabled.

        Mutual TLS (mTLS) cannot be used together with gateway authentication
        as they are mutually exclusive authentication mechanisms.

        Args:
            enable_gateway_auth: Boolean indicating if gateway auth is enabled, or None
            enable_mtls: Boolean indicating if mTLS is enabled, or None
            errors: Dictionary to accumulate validation errors

        Returns:
            None (modifies errors dict in place)
        """
        if enable_mtls and enable_gateway_auth:
            errors.setdefault('enable_mtls', []).append(ErrorDetail(_("Mutual TLS can only be enabled when gateway auth is disabled"), code='invalid'))

    def _validate_request_timeout_seconds(self, request_timeout_seconds: Optional[int], errors: Dict[str, List[ErrorDetail]]) -> None:
        """
        Validate that request_timeout_seconds is not below the effective floor.

        The floor is the global request_timeout preference. Routes can only
        extend timeouts beyond the global default, not reduce them.

        Args:
            request_timeout_seconds: The per-route timeout value, or None to skip validation
            errors: Dictionary to accumulate validation errors

        Returns:
            None (modifies errors dict in place)
        """
        if request_timeout_seconds is None:
            return

        floor = get_preference_value('proxy', 'request_timeout')
        if request_timeout_seconds < floor:
            errors.setdefault('request_timeout_seconds', []).append(
                ErrorDetail(
                    _("Value must be greater than or equal to the global %(pref_name)s setting (%(floor)s seconds).")
                    % {'pref_name': 'request_timeout', 'floor': floor},
                    code='invalid',
                )
            )

    def _validate_idle_timeout_seconds(self, idle_timeout_seconds: Optional[int], errors: Dict[str, List[ErrorDetail]]) -> None:
        """
        Validate that idle_timeout_seconds is not below the effective floor.

        The floor is the global idle_timeout preference. Routes can only
        extend timeouts beyond the global default, not reduce them.

        Args:
            idle_timeout_seconds: The per-route idle timeout value, or None to skip validation
            errors: Dictionary to accumulate validation errors

        Returns:
            None (modifies errors dict in place)
        """
        if idle_timeout_seconds is None:
            return

        floor = get_preference_value('proxy', 'idle_timeout')
        if idle_timeout_seconds < floor:
            errors.setdefault('idle_timeout_seconds', []).append(
                ErrorDetail(
                    _("Value must be greater than or equal to the global %(pref_name)s setting (%(floor)s seconds).")
                    % {'pref_name': 'idle_timeout', 'floor': floor},
                    code='invalid',
                )
            )

    def validate(self, attrs):
        """
        Perform validation for route configuration.

        Validates gateway authentication settings, mTLS settings, timeout floors,
        and normalizes paths. For PATCH operations, merges incoming data with
        instance values to ensure complete validation.

        Subclasses can override this method and call super().validate()
        to add their own validation logic.

        Args:
            attrs: Dictionary of attributes to validate

        Returns:
            Validated attributes dictionary

        Raises:
            ValidationError: If validation fails
        """
        # For PATCH updates, merge incoming data with instance values
        if self.instance:
            enable_gateway_auth = attrs.get('enable_gateway_auth', self.instance.enable_gateway_auth)
            is_internal_route = attrs.get('is_internal_route', self.instance.is_internal_route)
            enable_mtls = attrs.get('enable_mtls', self.instance.enable_mtls)
            request_timeout_seconds = attrs.get('request_timeout_seconds', self.instance.request_timeout_seconds)
            idle_timeout_seconds = attrs.get('idle_timeout_seconds', self.instance.idle_timeout_seconds)
        else:
            enable_gateway_auth = attrs.get('enable_gateway_auth')
            is_internal_route = attrs.get('is_internal_route')
            enable_mtls = attrs.get('enable_mtls', False)
            request_timeout_seconds = attrs.get('request_timeout_seconds')
            idle_timeout_seconds = attrs.get('idle_timeout_seconds')

        errors = {}

        # Validate internal route requires gateway auth
        self._validate_gateway_auth_if_internal_route(enable_gateway_auth, is_internal_route, errors)

        # Validate mTLS and gateway auth are mutually exclusive
        self._validate_gateway_auth_if_mtls_enabled(enable_gateway_auth, enable_mtls, errors)

        # Validate timeout floors against global preferences
        self._validate_request_timeout_seconds(request_timeout_seconds, errors)
        self._validate_idle_timeout_seconds(idle_timeout_seconds, errors)

        # Normalize gateway path by collapsing consecutive slashes
        if 'gateway_path' in attrs:
            attrs['gateway_path'] = remove_multiple_slashes_from_path(attrs['gateway_path'])

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
