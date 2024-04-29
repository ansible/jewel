# from rest_framework import serializers
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.rbac.api.related import RelatedAccessMixin
from ansible_base.rbac.policies import visible_users

from aap_gateway_api.models import Organization, Team


class TeamSerializer(RelatedAccessMixin, NamedCommonModelSerializer):
    lookup_field = 'users'

    class Meta:
        model = Team
        fields = NamedCommonModelSerializer.Meta.fields + [
            'organization',
            'users',
            'admins',
            'parents',
            'description',
        ]
        lookup_field = 'users'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            self.fields['organization'].queryset = Organization.access_qs(request.user)
            for related_name in ('users', 'admins'):
                self.fields[related_name].queryset = visible_users(request.user)
                self.fields[related_name].child_relation.queryset = visible_users(request.user)

    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()
        request = self.context.get('request')
        if request and request.user.is_superuser:
            return extra_kwargs

        view = self.context.get('view')
        if view:
            action = view.action

            if action in ['create', 'update', 'partial_update']:
                kwargs = extra_kwargs.get('organization')
                kwargs['read_only'] = action in ['update', 'partial_update']
                extra_kwargs['organization'] = kwargs

        return extra_kwargs
