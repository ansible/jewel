from aap_gateway_api.models import Team
from aap_gateway_api.serializers import NamedCommonModelSerializer


class TeamSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'team-detail'
    lookup_field = 'users'

    class Meta:
        model = Team
        fields = NamedCommonModelSerializer.Meta.fields + (
            'organization',
            'users',
        )
        lookup_field = 'users'
