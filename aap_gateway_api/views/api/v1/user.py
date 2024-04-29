from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.policies import visible_users
from rest_framework.decorators import action
from rest_framework.response import Response

from aap_gateway_api.models import User
from aap_gateway_api.serializers import UserSerializer
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ResourceAPIUpdateMixin


class UserViewSet(ResourceAPIUpdateMixin, GatewayModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    model = User
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        return super().filter_queryset(qs)

    @action(detail=True, methods=["get"], url_name="authenticators-list")
    def authenticators(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(status=404)
        queryset = Authenticator.objects.filter(authenticator_providers__user=user)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = AuthenticatorSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        data = AuthenticatorSerializer(queryset, many=True).data
        return Response(data)


class OrganizationUserViewSet(UserViewSet):
    """
    Shows all users for sublists like /api/v1/organizations/5/users/
    the related view still checks organization view permission
    """

    deprecated = True
    queryset = User.objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]
