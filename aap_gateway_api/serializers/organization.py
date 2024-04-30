from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.rbac.policies import visible_users

from aap_gateway_api.models import Organization


class OrganizationSerializer(NamedCommonModelSerializer):
    class Meta:
        model = Organization
        fields = NamedCommonModelSerializer.Meta.fields + [
            'description',
            'users',
            'admins',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            for related_name in ('users', 'admins'):
                self.fields[related_name].queryset = visible_users(request.user)
                self.fields[related_name].child_relation.queryset = visible_users(request.user)
