from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.contrib.auth import get_user_model
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

User = get_user_model()


class MeViewSet(viewsets.ReadOnlyModelViewSet, AnsibleBaseView):
    model = User
    serializer_class = UserSerializer
    permission_classes = [OAuth2ScopePermission, IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(username=self.request.user.username)
