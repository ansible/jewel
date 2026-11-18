from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from aap_gateway_api.models import DomainDefinition, UserPreference
from aap_gateway_api.serializers import UserPreferenceSerializer
from aap_gateway_api.services.domains import get_effective_domains


class UserPreferenceView(APIView):
    permission_classes = [OAuth2ScopePermission, IsAuthenticated]

    def get_object(self, request, preference_name):
        return UserPreference.objects.filter(user=request.user, name=preference_name).first()

    @extend_schema(responses=UserPreferenceSerializer)
    def get(self, request, preference_name):
        preference = self.get_object(request, preference_name)
        if preference is None:
            if preference_name == 'domains':
                effective_domains = get_effective_domains(request.user)
                if effective_domains:
                    return Response({'name': preference_name, 'value': {'domains': effective_domains, 'userDomains': [], 'activeDomains': []}})
            return Response({'name': preference_name, 'value': None})
        data = UserPreferenceSerializer(preference).data
        if preference_name == 'domains':
            data['value']['userDomains'] = preference.value.get('domains', [])
            data['value']['domains'] = get_effective_domains(request.user, data['value']['userDomains'])
        return Response(data)

    @extend_schema(request=UserPreferenceSerializer, responses=UserPreferenceSerializer)
    def put(self, request, preference_name):
        serializer = UserPreferenceSerializer(
            data=request.data,
            context={'preference_name': preference_name},
        )
        serializer.is_valid(raise_exception=True)
        preference, _created = UserPreference.objects.update_or_create(
            user=request.user,
            name=preference_name,
            defaults={'value': serializer.validated_data['value']},
        )
        if preference_name == 'domains':
            DomainDefinition.objects.update_or_create(
                scope=DomainDefinition.USER,
                user=request.user,
                defaults={'domains': serializer.validated_data['value']['domains']},
            )
            response = UserPreferenceSerializer(preference).data
            response['value']['userDomains'] = preference.value['domains']
            response['value']['domains'] = get_effective_domains(request.user, preference.value['domains'])
            return Response(response)
        return Response(UserPreferenceSerializer(preference).data)

    def delete(self, request, preference_name):
        preference = get_object_or_404(UserPreference, user=request.user, name=preference_name)
        preference.delete()
        if preference_name == 'domains':
            DomainDefinition.objects.filter(scope=DomainDefinition.USER, user=request.user).delete()
        return Response(status=204)
