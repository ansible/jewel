from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from aap_gateway_api.utils.preferences import get_preference_value
from aap_gateway_api.views.api.v1.common import AnsibleBaseView


class UIConfigView(AnsibleBaseView):
    permission_classes = [OAuth2ScopePermission, IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                'UIConfig',
                fields={'personal_access_tokens_allowed': serializers.BooleanField()},
            ),
        },
    )
    def get(self, request, format=None):
        allow_local_pat_creation = get_preference_value('oauth2_provider', 'allow_local_pat_creation')
        return Response({'personal_access_tokens_allowed': allow_local_pat_creation})
