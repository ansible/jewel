from ansible_base.lib.serializers.common import NamedCommonModelSerializer

from aap_gateway_api.models import Team


class TeamSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'team-detail'
    lookup_field = 'users'

    class Meta:
        model = Team
        fields = NamedCommonModelSerializer.Meta.fields + [
            'organization',
            'users',
        ]
        lookup_field = 'users'
