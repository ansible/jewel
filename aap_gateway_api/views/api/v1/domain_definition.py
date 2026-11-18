from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from aap_gateway_api.models import DomainDefinition, Organization, Team
from aap_gateway_api.serializers import DomainDefinitionSerializer


class DomainDefinitionView(APIView):
    """Read and replace organization/team domain definitions."""

    permission_classes = [OAuth2ScopePermission, IsAuthenticated]

    def get_owner(self, scope, pk):
        model = Organization if scope == DomainDefinition.ORGANIZATION else Team
        return get_object_or_404(model, pk=pk)

    def can_change(self, request, owner):
        return request.user.is_superuser or owner.admins.filter(pk=request.user.pk).exists()

    def can_view(self, request, owner):
        return request.user.is_superuser or owner.users.filter(pk=request.user.pk).exists() or owner.admins.filter(pk=request.user.pk).exists()

    def get(self, request, scope, pk):
        owner = self.get_owner(scope, pk)
        if not self.can_view(request, owner):
            return Response({'detail': 'You do not have permission to view this domain definition.'}, status=403)
        definition = DomainDefinition.objects.filter(**{scope: owner}).first()
        return Response({'scope': scope, 'domains': definition.domains if definition else []})

    def put(self, request, scope, pk):
        owner = self.get_owner(scope, pk)
        if not self.can_change(request, owner):
            return Response({'detail': 'You do not have permission to change this domain definition.'}, status=403)
        serializer = DomainDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        definition, _created = DomainDefinition.objects.update_or_create(
            **{'scope': scope, scope: owner},
            defaults={'domains': serializer.validated_data['domains']},
        )
        return Response(DomainDefinitionSerializer(definition).data)
