"""API endpoint for managing feature flags."""

import logging

from ansible_base.feature_flags.views import AAPFlag
from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.serializers.feature_flags import FeatureFlagPatchSerializer, FeatureFlagSerializer
from aap_gateway_api.utils import get_preference_value
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin

logger = logging.getLogger(__name__)


class AAPFlagViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    """API endpoint that allows feature flags to be viewed or edited."""

    queryset = AAPFlag.objects.order_by('id')
    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the action."""
        if self.action == 'partial_update':
            return FeatureFlagPatchSerializer
        return FeatureFlagSerializer

    def partial_update(self, request, **kwargs):
        """Handle PATCH requests to update feature flag values."""
        _feature_flag = self.get_object()
        value = request.data.get('value')
        if not value:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": "Invalid request object."})

        if not get_preference_value('feature_flags', 'RUNTIME_FEATURE_FLAGS', encrypted=False):
            return Response(
                status=status.HTTP_403_FORBIDDEN, data={"details": "To allow run-time feature flag updates, RUNTIME_FEATURE_FLAGS must be set to 'True'."}
            )

        feature_flag = get_object_or_404(AAPFlag, pk=_feature_flag.id)

        # Check if the flag is locked by install-time configuration
        # Install-time specified values take precedence and make the flag read-only
        if hasattr(settings, feature_flag.name) and isinstance(getattr(settings, feature_flag.name), bool):
            return Response(
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
                data={
                    "details": "This feature flag was set at install-time and cannot be modified at runtime. "
                    "To change this flag, update the install-time configuration and rerun the installer."
                },
            )

        if feature_flag.toggle_type == 'install-time':
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED, data={"details": "Install-time feature flags cannot be toggled at run-time."})
        if feature_flag.condition == "boolean":
            try:
                to_python_boolean(value)
            except ValueError:
                return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": "Feature flag boolean conditional requires using boolean value."})
        else:
            logger.error(f"The aap_flag view only know how to deal with boolean condition flags. We got {feature_flag.condition}")
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"details": f"Feature flag was passed with condition {feature_flag.condition} which can only be boolean."},
            )
        return super().partial_update(request, **kwargs)
