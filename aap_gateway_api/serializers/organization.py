from aap_gateway_api.models import Organization
from aap_gateway_api.serializers import NamedCommonModelSerializer


class OrganizationSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'organization-detail'

    class Meta:
        model = Organization
        fields = NamedCommonModelSerializer.Meta.fields + ('environment',)
