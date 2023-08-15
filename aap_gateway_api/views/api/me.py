from django.contrib.auth import get_user_model
from rest_framework import mixins, permissions, viewsets

from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.common import ViewWithHeaders

User = get_user_model()


class MeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet, ViewWithHeaders):
    model = User
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(username=self.request.user.username)
